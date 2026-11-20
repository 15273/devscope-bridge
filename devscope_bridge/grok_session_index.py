"""Discover Grok CLI sessions under ~/.grok/sessions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

SOURCE_GROK = "grok"
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


def default_grok_home() -> Path:
    return Path.home() / ".grok"


def import_slug(session_id: str) -> str:
    compact = session_id.replace("-", "")[:8].lower()
    return f"gk-{compact}"


def allocate_import_name(session_id: str, taken: set[str]) -> str:
    base = import_slug(session_id)
    if base not in taken:
        return base
    for i in range(2, 100):
        candidate = f"{base}-{i}"
        if candidate not in taken:
            return candidate
    raise RuntimeError(f"could not allocate a session name for {session_id}")


def _clip(text: str) -> str:
    text = " ".join(text.split())
    return text[:_TITLE_MAX] if text else "Grok session"


def _from_summary(path: Path) -> DiscoveredSession | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    info = raw.get("info") if isinstance(raw.get("info"), dict) else {}
    sid = str(info.get("id") or path.parent.name).strip()
    if not sid:
        return None
    cwd = str(info.get("cwd") or "")
    title = str(
        raw.get("generated_title")
        or raw.get("session_summary")
        or raw.get("last_turn_summary")
        or ""
    ).strip()
    last_used = str(raw.get("last_active_at") or raw.get("updated_at") or "")
    return DiscoveredSession(
        session_id=sid,
        title=_clip(title) if title else _clip(sid),
        cwd=cwd,
        source=SOURCE_GROK,
        last_used=last_used,
        can_resume=True,
        transcript_path=str(path.parent / "updates.jsonl"),
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
    grok_home: Path | None = None,
    limit: int = DISCOVER_LIMIT,
    owner_lookup: Callable[[str], str | None] | None = None,
) -> list[DiscoveredSession]:
    home = grok_home if grok_home is not None else default_grok_home()
    root = home / "sessions"
    items: list[DiscoveredSession] = []
    if root.is_dir():
        for summary in root.glob("*/*/summary.json"):
            if "subagents" in summary.parts:
                continue
            item = _from_summary(summary)
            if item is not None:
                items.append(item)
    items.sort(key=lambda x: x.last_used, reverse=True)
    lookup = owner_lookup or _default_owner
    return [_with_owner(item, lookup) for item in items[: max(0, limit)]]


def lookup_session(
    session_id: str,
    *,
    grok_home: Path | None = None,
    owner_lookup: Callable[[str], str | None] | None = None,
) -> DiscoveredSession | None:
    if not session_id:
        return None
    for item in discover_sessions(grok_home=grok_home, owner_lookup=owner_lookup):
        if item.session_id == session_id:
            return item
    return None
