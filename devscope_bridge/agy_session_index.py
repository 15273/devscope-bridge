"""Discover Antigravity CLI + IDE conversations. Never decode encrypted .pb."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from devscope_bridge.agents import SOURCE_ANTIGRAVITY_CLI, SOURCE_ANTIGRAVITY_IDE

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
    seed_summary: str | None = None


def default_cli_root() -> Path:
    return Path.home() / ".gemini" / "antigravity-cli"


def default_ide_root() -> Path:
    return Path.home() / ".gemini" / "antigravity"


def import_slug(source: str, session_id: str) -> str:
    prefix = "ag" if source == SOURCE_ANTIGRAVITY_CLI else "ai"
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


def _clip(text: str) -> str:
    text = " ".join(text.split())
    return text[:_TITLE_MAX] if text else "Antigravity session"


def _iso_mtime(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
    except OSError:
        return ""


def _title_from_md(path: Path) -> str:
    try:
        for line in path.read_text(errors="replace").splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                return _clip(stripped.lstrip("# ").strip())
            if stripped:
                return _clip(stripped)
    except OSError:
        pass
    return ""


def _seed_from_brain(brain_dir: Path) -> str:
    parts: list[str] = []
    for name in ("task.md", "implementation_plan.md", "walkthrough.md"):
        path = brain_dir / name
        if not path.is_file():
            continue
        try:
            text = path.read_text(errors="replace").strip()
        except OSError:
            continue
        if text:
            parts.append(f"## {name}\n{text[:4000]}")
    return "\n\n".join(parts)


def _cli_items(root: Path) -> list[DiscoveredSession]:
    items: list[DiscoveredSession] = []
    hist = root / "history.jsonl"
    seen: set[str] = set()
    if hist.is_file():
        try:
            for line in hist.read_text(errors="replace").splitlines():
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(obj, dict):
                    continue
                sid = obj.get("conversationId") or obj.get("conversation_id")
                if not isinstance(sid, str) or sid in seen:
                    continue
                seen.add(sid)
                title = str(obj.get("display") or obj.get("title") or sid)
                cwd = str(obj.get("workspace") or obj.get("cwd") or "")
                last_used = str(obj.get("timestamp") or "")
                items.append(DiscoveredSession(
                    session_id=sid,
                    title=_clip(title),
                    cwd=cwd,
                    source=SOURCE_ANTIGRAVITY_CLI,
                    last_used=last_used,
                    can_resume=True,
                ))
        except OSError:
            pass
    brain = root / "brain"
    if brain.is_dir():
        for child in brain.iterdir():
            if not child.is_dir() or child.name in seen:
                continue
            task = child / "task.md"
            title = _title_from_md(task) if task.is_file() else child.name
            items.append(DiscoveredSession(
                session_id=child.name,
                title=_clip(title),
                cwd="",
                source=SOURCE_ANTIGRAVITY_CLI,
                last_used=_iso_mtime(child),
                can_resume=True,
            ))
    return items


def _ide_items(root: Path) -> list[DiscoveredSession]:
    items: list[DiscoveredSession] = []
    conv = root / "conversations"
    brain = root / "brain"
    ids: set[str] = set()
    if conv.is_dir():
        for path in conv.glob("*.pb"):
            ids.add(path.stem)
    if brain.is_dir():
        for child in brain.iterdir():
            if child.is_dir():
                ids.add(child.name)
    for sid in ids:
        brain_dir = brain / sid
        task = brain_dir / "task.md"
        meta = brain_dir / "task.md.metadata.json"
        title = ""
        cwd = ""
        if meta.is_file():
            try:
                obj = json.loads(meta.read_text())
                if isinstance(obj, dict):
                    title = str(obj.get("title") or obj.get("name") or "")
                    cwd = str(obj.get("cwd") or obj.get("workspace") or "")
            except (OSError, json.JSONDecodeError):
                pass
        if not title and task.is_file():
            title = _title_from_md(task)
        stamp_path = conv / f"{sid}.pb" if (conv / f"{sid}.pb").is_file() else brain_dir
        items.append(DiscoveredSession(
            session_id=sid,
            title=_clip(title) if title else _clip(sid),
            cwd=cwd,
            source=SOURCE_ANTIGRAVITY_IDE,
            last_used=_iso_mtime(stamp_path) if stamp_path.exists() else "",
            can_resume=False,
            seed_summary=_seed_from_brain(brain_dir) if brain_dir.is_dir() else None,
        ))
    return items


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
        seed_summary=item.seed_summary,
    )


def discover_sessions(
    *,
    cli_root: Path | None = None,
    ide_root: Path | None = None,
    limit: int = DISCOVER_LIMIT,
    owner_lookup: Callable[[str], str | None] | None = None,
) -> list[DiscoveredSession]:
    items = _cli_items(cli_root or default_cli_root()) + _ide_items(ide_root or default_ide_root())
    items.sort(key=lambda x: x.last_used, reverse=True)
    lookup = owner_lookup or _default_owner
    return [_with_owner(item, lookup) for item in items[: max(0, limit)]]


def lookup_session(
    session_id: str,
    source: str | None = None,
    *,
    cli_root: Path | None = None,
    ide_root: Path | None = None,
    owner_lookup: Callable[[str], str | None] | None = None,
) -> DiscoveredSession | None:
    if not session_id:
        return None
    for item in discover_sessions(
        cli_root=cli_root, ide_root=ide_root, owner_lookup=owner_lookup,
    ):
        if item.session_id == session_id and (source is None or item.source == source):
            return item
    return None
