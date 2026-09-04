"""Discover Claude Code / Desktop sessions on disk for import into DevScope.

Does not read ~/.claude.json, history.jsonl, or Desktop oauth caches.
Cwd comes from JSONL / sidecar fields — never from encoded folder names.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator

DISCOVER_LIMIT = 150
_HEAD_BYTES = 65_536
_TAIL_BYTES = 65_536
_TITLE_MAX = 80

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

SOURCE_CLAUDE_CODE = "claude_code"
SOURCE_DESKTOP_CODE = "desktop_code"
SOURCE_DESKTOP_LOCAL = "desktop_local"

_SLUG_PREFIX = {
    SOURCE_CLAUDE_CODE: "cc",
    SOURCE_DESKTOP_CODE: "dc",
    SOURCE_DESKTOP_LOCAL: "dl",
}


@dataclass(frozen=True)
class DiscoveredSession:
    session_id: str
    title: str
    cwd: str
    source: str
    last_used: str
    can_resume: bool
    config_dir: str | None = None
    transcript_path: str | None = None
    title_source: str = "first-user"
    already_imported: bool = False
    bridge_name: str | None = None


def default_claude_home() -> Path:
    return Path.home() / ".claude"


def default_desktop_code_root() -> Path:
    return Path.home() / "Library" / "Application Support" / "Claude" / "claude-code-sessions"


def default_desktop_local_root() -> Path:
    return (
        Path.home()
        / "Library"
        / "Application Support"
        / "Claude"
        / "local-agent-mode-sessions"
    )


def import_slug(source: str, session_id: str) -> str:
    prefix = _SLUG_PREFIX.get(source, "cc")
    hex8 = session_id.replace("-", "")[:8].lower()
    return f"{prefix}-{hex8}"


def allocate_import_name(source: str, session_id: str, taken: set[str]) -> str:
    base = import_slug(source, session_id)
    if base not in taken:
        return base
    for i in range(2, 100):
        candidate = f"{base}-{i}"
        if candidate not in taken:
            return candidate
    raise RuntimeError(f"could not allocate a session name for {session_id}")


def discover_sessions(
    *,
    claude_home: Path | None = None,
    desktop_code_root: Path | None = None,
    desktop_local_root: Path | None = None,
    limit: int = DISCOVER_LIMIT,
    owner_lookup: Callable[[str], str | None] | None = None,
) -> list[DiscoveredSession]:
    items = _merge_by_id(
        _iter_all(
            claude_home=claude_home,
            desktop_code_root=desktop_code_root,
            desktop_local_root=desktop_local_root,
        )
    )
    items.sort(key=lambda x: x.last_used, reverse=True)
    capped = items[: max(0, limit)]
    lookup = owner_lookup or _default_owner
    return [_with_owner(item, lookup) for item in capped]


def lookup_session(
    session_id: str,
    source: str | None = None,
    *,
    claude_home: Path | None = None,
    desktop_code_root: Path | None = None,
    desktop_local_root: Path | None = None,
    owner_lookup: Callable[[str], str | None] | None = None,
) -> DiscoveredSession | None:
    if not session_id:
        return None
    merged = _merge_by_id(
        _iter_all(
            claude_home=claude_home,
            desktop_code_root=desktop_code_root,
            desktop_local_root=desktop_local_root,
        )
    )
    lookup = owner_lookup or _default_owner
    any_match: DiscoveredSession | None = None
    for item in merged:
        if item.session_id != session_id:
            continue
        if not source or item.source == source:
            return _with_owner(item, lookup)
        any_match = item
    return _with_owner(any_match, lookup) if any_match else None


def _default_owner(session_id: str) -> str | None:
    from devscope_bridge import session_store
    return session_store.session_id_owner(session_id)


def _with_owner(
    item: DiscoveredSession,
    owner_lookup: Callable[[str], str | None],
) -> DiscoveredSession:
    owner = owner_lookup(item.session_id)
    if not owner:
        return item
    return DiscoveredSession(
        session_id=item.session_id,
        title=item.title,
        cwd=item.cwd,
        source=item.source,
        last_used=item.last_used,
        can_resume=item.can_resume,
        config_dir=item.config_dir,
        transcript_path=item.transcript_path,
        title_source=item.title_source,
        already_imported=True,
        bridge_name=owner,
    )


def _iter_all(
    *,
    claude_home: Path | None,
    desktop_code_root: Path | None,
    desktop_local_root: Path | None,
) -> Iterator[DiscoveredSession]:
    home = claude_home if claude_home is not None else default_claude_home()
    code_root = desktop_code_root if desktop_code_root is not None else default_desktop_code_root()
    local_root = desktop_local_root if desktop_local_root is not None else default_desktop_local_root()
    yield from _iter_global_jsonl(home)
    yield from _iter_desktop_sidecars(code_root, source=SOURCE_DESKTOP_CODE, claude_home=home)
    yield from _iter_desktop_sidecars(local_root, source=SOURCE_DESKTOP_LOCAL, claude_home=home)


def _merge_by_id(items: Iterator[DiscoveredSession]) -> list[DiscoveredSession]:
    by_id: dict[str, DiscoveredSession] = {}
    for item in items:
        existing = by_id.get(item.session_id)
        by_id[item.session_id] = item if existing is None else _overlay(existing, item)
    return list(by_id.values())


def _overlay(base: DiscoveredSession, incoming: DiscoveredSession) -> DiscoveredSession:
    sidecar_in = incoming.title_source == "sidecar"
    sidecar_base = base.title_source == "sidecar"
    if sidecar_in and incoming.title:
        title, title_source = incoming.title, incoming.title_source
    elif sidecar_base and base.title:
        title, title_source = base.title, base.title_source
    elif incoming.title and (not base.title or incoming.title_source == "custom-title"):
        title, title_source = incoming.title, incoming.title_source
    else:
        title, title_source = base.title or incoming.title, base.title_source

    source = incoming.source if incoming.source != SOURCE_CLAUDE_CODE else base.source
    if base.source != SOURCE_CLAUDE_CODE and incoming.source == SOURCE_CLAUDE_CODE:
        source = base.source

    return DiscoveredSession(
        session_id=base.session_id,
        title=title or incoming.title or base.session_id[:8],
        cwd=_prefer_real_cwd(incoming.cwd, base.cwd),
        source=source,
        last_used=_later(incoming.last_used, base.last_used),
        can_resume=base.can_resume or incoming.can_resume,
        config_dir=incoming.config_dir or base.config_dir,
        transcript_path=incoming.transcript_path or base.transcript_path,
        title_source=title_source,
    )


def _prefer_real_cwd(a: str, b: str) -> str:
    if a and os.path.isdir(a) and not _looks_like_sandbox(a):
        return a
    if b and os.path.isdir(b) and not _looks_like_sandbox(b):
        return b
    if a and os.path.isdir(a):
        return a
    if b and os.path.isdir(b):
        return b
    return a or b


def _looks_like_sandbox(path: str) -> bool:
    return "local-agent-mode-sessions" in path or path.startswith("/sessions/")


def _later(a: str, b: str) -> str:
    return a if a >= b else b


def _iter_global_jsonl(claude_home: Path) -> Iterator[DiscoveredSession]:
    projects = claude_home / "projects"
    if not projects.is_dir():
        return
    for path in projects.glob("*/*.jsonl"):
        if "subagents" in path.parts:
            continue
        if not _UUID_RE.match(path.stem):
            continue
        try:
            if path.stat().st_size <= 0:
                continue
        except OSError:
            continue
        yield _item_from_jsonl(path, source=SOURCE_CLAUDE_CODE, config_dir=None)


def _iter_desktop_sidecars(
    root: Path,
    *,
    source: str,
    claude_home: Path,
) -> Iterator[DiscoveredSession]:
    if not root.is_dir():
        return
    for sidecar in root.glob("*/*/local_*.json"):
        if ".claude" in sidecar.parts:
            continue
        item = _item_from_sidecar(sidecar, source=source, claude_home=claude_home)
        if item is not None:
            yield item


def _item_from_sidecar(
    sidecar: Path,
    *,
    source: str,
    claude_home: Path,
) -> DiscoveredSession | None:
    try:
        raw = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict) or raw.get("isArchived") is True:
        return None
    session_id = str(raw.get("cliSessionId") or "").strip()
    if not session_id or not _UUID_RE.match(session_id):
        return None

    sandbox = sidecar.with_suffix("")
    isolated_claude = sandbox / ".claude"
    jsonl = _find_jsonl(claude_home / "projects", session_id)
    if jsonl is None and isolated_claude.is_dir():
        jsonl = _find_jsonl(isolated_claude / "projects", session_id)

    peeked = _peek_jsonl(jsonl) if jsonl is not None else {}
    title = str(raw.get("title") or "").strip() or peeked.get("title") or session_id[:8]
    title_source = "sidecar" if raw.get("title") else peeked.get("title_source") or "sidecar"

    cwd = _prefer_real_cwd(
        str(raw.get("originCwd") or "").strip(),
        str(peeked.get("cwd") or raw.get("cwd") or "").strip(),
    )
    last_used = _iso_from_sidecar_time(raw, sidecar)
    config_dir = str(isolated_claude) if isolated_claude.is_dir() else None
    can_resume = jsonl is not None or bool(session_id and config_dir)

    return DiscoveredSession(
        session_id=session_id,
        title=_clip(title, _TITLE_MAX),
        cwd=cwd,
        source=source,
        last_used=last_used,
        can_resume=can_resume,
        config_dir=config_dir,
        transcript_path=str(jsonl) if jsonl else None,
        title_source=title_source,
    )


def _item_from_jsonl(
    path: Path,
    *,
    source: str,
    config_dir: str | None,
) -> DiscoveredSession:
    peeked = _peek_jsonl(path)
    title = peeked.get("title") or path.stem[:8]
    last_used = peeked.get("timestamp") or _iso_from_mtime(path)
    return DiscoveredSession(
        session_id=path.stem,
        title=_clip(str(title), _TITLE_MAX),
        cwd=str(peeked.get("cwd") or ""),
        source=source,
        last_used=_as_iso(last_used),
        can_resume=True,
        config_dir=config_dir,
        transcript_path=str(path),
        title_source=str(peeked.get("title_source") or "first-user"),
    )


def _find_jsonl(projects: Path, session_id: str) -> Path | None:
    if not projects.is_dir():
        return None
    matches = list(projects.glob(f"*/{session_id}.jsonl"))
    return matches[0] if matches else None


def _peek_jsonl(path: Path) -> dict:
    result: dict = {
        "title": None,
        "title_source": None,
        "cwd": None,
        "timestamp": None,
    }
    try:
        lines = _head_tail_lines(path)
    except OSError:
        return result
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(rec, dict):
            continue
        typ = rec.get("type")
        if rec.get("cwd") and not result["cwd"]:
            result["cwd"] = rec["cwd"]
        ts = rec.get("timestamp")
        if ts:
            result["timestamp"] = ts
        if typ == "custom-title" and rec.get("customTitle"):
            result["title"] = rec["customTitle"]
            result["title_source"] = "custom-title"
        elif typ == "last-prompt" and rec.get("lastPrompt") and result["title_source"] != "custom-title":
            result["title"] = rec["lastPrompt"]
            result["title_source"] = "last-prompt"
        elif typ == "summary" and rec.get("summary") and result["title_source"] not in (
            "custom-title",
            "last-prompt",
        ):
            result["title"] = rec["summary"]
            result["title_source"] = "summary"
        elif typ == "user" and result["title_source"] not in (
            "custom-title",
            "last-prompt",
            "summary",
        ):
            text = _message_text(rec)
            if text and result["title"] is None:
                result["title"] = text
                result["title_source"] = "first-user"
    return result


def _head_tail_lines(path: Path) -> list[str]:
    size = path.stat().st_size
    with path.open("rb") as fh:
        head = fh.read(_HEAD_BYTES)
        tail = b""
        if size > _HEAD_BYTES + _TAIL_BYTES:
            fh.seek(max(0, size - _TAIL_BYTES))
            tail = fh.read(_TAIL_BYTES)
        elif size > _HEAD_BYTES:
            tail = fh.read()
    lines = head.decode("utf-8", "replace").splitlines()
    if tail:
        tail_lines = tail.decode("utf-8", "replace").splitlines()
        if tail_lines:
            lines.extend(tail_lines[1:])
    return lines


def _message_text(rec: dict) -> str:
    content = rec.get("message", {}).get("content") if isinstance(rec.get("message"), dict) else None
    if content is None:
        content = rec.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [
            b.get("text", "")
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        ]
        return "\n".join(p for p in parts if p).strip()
    return ""


def _clip(text: str, n: int) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= n:
        return cleaned
    return cleaned[: n - 1].rstrip() + "…"


def _iso_from_mtime(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
    except OSError:
        return datetime.now(tz=timezone.utc).isoformat()


def _iso_from_sidecar_time(raw: dict, sidecar: Path) -> str:
    for key in ("lastActivityAt", "lastFocusedAt", "createdAt"):
        value = raw.get(key)
        if value:
            return _as_iso(value)
    return _iso_from_mtime(sidecar)


def _as_iso(value: object) -> str:
    if isinstance(value, (int, float)) and value > 0:
        seconds = value / 1000.0 if value > 1e12 else float(value)
        return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()
    if isinstance(value, str) and value:
        return value
    return datetime.now(tz=timezone.utc).isoformat()
