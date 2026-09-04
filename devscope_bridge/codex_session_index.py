"""Discover Codex CLI sessions on disk. Does not read auth.json or sqlite creds."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from devscope_bridge.agents import SOURCE_CODEX

DISCOVER_LIMIT = 150
_TITLE_MAX = 80


@dataclass(frozen=True)
class DiscoveredSession:
    session_id: str
    title: str
    cwd: str
    source: str
    last_used: str
    can_resume: bool
    already_imported: bool = False
    bridge_name: str | None = None
    transcript_path: str | None = None


def default_codex_home() -> Path:
    return Path.home() / ".codex"


def import_slug(session_id: str) -> str:
    hex8 = session_id.replace("-", "")[:8].lower()
    return f"cx-{hex8}"


def allocate_import_name(session_id: str, taken: set[str]) -> str:
    base = import_slug(session_id)
    if base not in taken:
        return base
    for i in range(2, 100):
        candidate = f"{base}-{i}"
        if candidate not in taken:
            return candidate
    raise RuntimeError(f"could not allocate a session name for {session_id}")


def _iso(ts: object) -> str:
    if isinstance(ts, (int, float)):
        try:
            return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            return ""
    if isinstance(ts, str):
        return ts
    return ""


def _clip(text: str) -> str:
    text = " ".join(text.split())
    return text[:_TITLE_MAX] if text else "Codex session"


def _from_index_line(obj: dict) -> DiscoveredSession | None:
    sid = obj.get("id") or obj.get("thread_id") or obj.get("session_id")
    if not isinstance(sid, str) or not sid.strip():
        return None
    title = str(obj.get("thread_name") or obj.get("title") or "").strip()
    cwd = str(obj.get("cwd") or "")
    last_used = _iso(obj.get("updated_at") or obj.get("updatedAt") or obj.get("timestamp"))
    return DiscoveredSession(
        session_id=sid.strip(),
        title=_clip(title) if title else _clip(sid),
        cwd=cwd,
        source=SOURCE_CODEX,
        last_used=last_used,
        can_resume=True,
    )


def _from_rollout(path: Path) -> DiscoveredSession | None:
    sid = ""
    cwd = ""
    title = ""
    last_used = ""
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return None
    for line in text.splitlines()[:80]:
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        kind = obj.get("type")
        payload = obj.get("payload") if isinstance(obj.get("payload"), dict) else {}
        if kind == "session_meta":
            sid = str(payload.get("id") or payload.get("session_id") or sid)
            cwd = str(payload.get("cwd") or cwd)
            last_used = str(obj.get("timestamp") or last_used)
        if not title and kind in ("event_msg", "response_item"):
            inner = payload.get("item") if isinstance(payload.get("item"), dict) else payload
            itype = str(inner.get("type") or payload.get("type") or "")
            if itype in ("UserMessage", "user", "message") or inner.get("role") == "user":
                content = inner.get("text") or inner.get("content") or payload.get("text")
                if isinstance(content, list) and content:
                    first = content[0]
                    content = first.get("text") if isinstance(first, dict) else first
                if isinstance(content, str) and content.strip():
                    title = content.strip()
    if not sid:
        # rollout-YYYY-MM-DDTHH-MM-SS-<uuid>.jsonl
        stem = path.stem
        if "rollout-" in stem:
            sid = stem.split("rollout-", 1)[-1]
            parts = sid.split("-")
            if len(parts) >= 5:
                sid = "-".join(parts[-5:])
    if not sid:
        return None
    if path.stat().st_mtime:
        last_used = last_used or datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
    return DiscoveredSession(
        session_id=sid,
        title=_clip(title) if title else _clip(sid),
        cwd=cwd,
        source=SOURCE_CODEX,
        last_used=last_used,
        can_resume=True,
        transcript_path=str(path),
    )


def _default_owner(session_id: str) -> str | None:
    from devscope_bridge import session_store
    return session_store.session_id_owner(session_id)


def _with_owner(item: DiscoveredSession, lookup: Callable[[str], str | None]) -> DiscoveredSession:
    owner = lookup(item.session_id)
    if not owner:
        return item
    return DiscoveredSession(
        session_id=item.session_id,
        title=item.title,
        cwd=item.cwd,
        source=item.source,
        last_used=item.last_used,
        can_resume=item.can_resume,
        already_imported=True,
        bridge_name=owner,
        transcript_path=item.transcript_path,
    )


def discover_sessions(
    *,
    codex_home: Path | None = None,
    limit: int = DISCOVER_LIMIT,
    owner_lookup: Callable[[str], str | None] | None = None,
) -> list[DiscoveredSession]:
    home = codex_home or default_codex_home()
    by_id: dict[str, DiscoveredSession] = {}
    index_path = home / "session_index.jsonl"
    if index_path.is_file():
        try:
            for line in index_path.read_text(errors="replace").splitlines():
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict):
                    found = _from_index_line(obj)
                    if found:
                        by_id[found.session_id] = found
        except OSError:
            pass
    sessions_dir = home / "sessions"
    if sessions_dir.is_dir():
        for path in sessions_dir.rglob("rollout-*.jsonl"):
            found = _from_rollout(path)
            if not found:
                continue
            existing = by_id.get(found.session_id)
            if existing is None:
                by_id[found.session_id] = found
            else:
                title = existing.title if existing.title != _clip(existing.session_id) else found.title
                cwd = existing.cwd or found.cwd
                last_used = max(existing.last_used, found.last_used)
                by_id[found.session_id] = DiscoveredSession(
                    session_id=existing.session_id,
                    title=title,
                    cwd=cwd,
                    source=SOURCE_CODEX,
                    last_used=last_used,
                    can_resume=True,
                    transcript_path=found.transcript_path,
                )
    items = sorted(by_id.values(), key=lambda x: x.last_used, reverse=True)[: max(0, limit)]
    lookup = owner_lookup or _default_owner
    return [_with_owner(item, lookup) for item in items]


def lookup_session(
    session_id: str,
    *,
    codex_home: Path | None = None,
    owner_lookup: Callable[[str], str | None] | None = None,
) -> DiscoveredSession | None:
    if not session_id:
        return None
    for item in discover_sessions(codex_home=codex_home, owner_lookup=owner_lookup):
        if item.session_id == session_id:
            return item
    return None


def read_models_cache(codex_home: Path | None = None) -> list[dict]:
    home = codex_home or default_codex_home()
    path = home / "models_cache.json"
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    models = raw.get("models") if isinstance(raw, dict) else raw
    if not isinstance(models, list):
        return []
    out = []
    for item in models:
        if not isinstance(item, dict):
            continue
        mid = item.get("id") or item.get("slug") or item.get("name")
        if not mid or item.get("hidden"):
            continue
        out.append({"id": str(mid), "label": str(item.get("display_name") or item.get("label") or mid)})
    return out
