"""Live WhatsApp → SQLite hydration for the cockpit assistant."""

from __future__ import annotations

import logging
import sqlite3
import time
from typing import Any

from devscope_bridge import browser_relay
from devscope_bridge.whatsapp import cockpit_config, cockpit_store, whatsapp_engine

logger = logging.getLogger(__name__)

_STALE_S = 300  # re-fetch live messages if mirror older than 5 min


def messages_from_rows(rows: list) -> list[dict[str, Any]]:
    """Normalize SQLite rows to assistant-friendly dicts (oldest first)."""
    out: list[dict[str, Any]] = []
    for row in reversed(rows):
        d = dict(row)
        out.append({
            "id": d.get("id", ""),
            "text": d.get("text") or "",
            "from_me": bool(d.get("from_me")),
            "author": d.get("author") or "",
            "ts": int(d.get("ts") or 0),
        })
    return out


def _mirror_is_stale(db: sqlite3.Connection, chat_id: str) -> bool:
    row = db.execute(
        "SELECT MAX(ts) AS latest FROM messages WHERE chat_id=?",
        (chat_id,),
    ).fetchone()
    if not row or row["latest"] is None:
        return True
    return int(time.time()) - int(row["latest"]) > _STALE_S


async def pick_wa_session(preferred: str | None) -> str | None:
    """Route WA store ops to a connected DevScope session."""
    if preferred and preferred in browser_relay.candidate_sessions():
        return preferred
    return browser_relay.first_active_session()


async def upsert_chat_meta(
    db: sqlite3.Connection,
    chat_id: str,
    session: str | None,
    cfg: dict,
) -> bool:
    """Ensure chat row exists by scanning live chat list."""
    res = await whatsapp_engine.list_chats(limit=300, session=session, quiet=True)
    if not res.get("ok"):
        return False
    for chat in res.get("data") or []:
        if chat.get("id") == chat_id:
            in_scope = cockpit_config.is_in_scope(
                cfg, chat_id, is_group=bool(chat.get("isGroup")),
            )
            cockpit_store.upsert_chat(db, chat, in_scope=in_scope)
            return True
    return False


async def hydrate_chat_messages(
    db: sqlite3.Connection,
    chat_id: str,
    session: str | None,
    cfg: dict,
    *,
    limit: int = 40,
    force: bool = False,
) -> tuple[list[dict[str, Any]], str | None]:
    """Return messages oldest-first; fetch live when mirror empty or stale."""
    session = await pick_wa_session(session)
    if not cockpit_store.get_chat(db, chat_id):
        await upsert_chat_meta(db, chat_id, session, cfg)

    rows = cockpit_store.recent_messages(db, chat_id, limit)
    need_live = force or not rows or _mirror_is_stale(db, chat_id)

    if need_live and session:
        live = await whatsapp_engine.get_messages(
            chat_id, limit=limit, session=session, quiet=True,
        )
        if live.get("ok") and live.get("data"):
            cockpit_store.upsert_messages(db, chat_id, live["data"])
            rows = cockpit_store.recent_messages(db, chat_id, limit)
        elif live.get("error"):
            logger.warning("hydrate_chat_messages: live fetch failed: %s", live.get("error"))
            return messages_from_rows(rows), str(live.get("error"))

    return messages_from_rows(rows), None


async def wa_store_health(session: str | None = None) -> dict[str, Any]:
    """Probe live WhatsApp Store + mirror stats."""
    session = await pick_wa_session(session)
    live: dict[str, Any] = {"ok": False, "session": session}
    if session:
        res = await whatsapp_engine.list_chats(limit=5, session=session, quiet=True)
        live = {
            "ok": bool(res.get("ok")),
            "session": session,
            "error": res.get("error"),
            "sample_chats": len(res.get("data") or []),
        }
    return live
