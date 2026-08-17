"""cockpit_poller.py — Background loop mirroring live WhatsApp into SQLite.

Snapshots in-scope chats via whatsapp_engine, writes to the cockpit SQLite
store, recomputes nudges, and persists them. The loop never dies on exception
— any tick failure is logged and the loop sleeps until the next interval.
"""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from fastapi import HTTPException

from devscope_bridge import browser_relay
from devscope_bridge.whatsapp import (
    cockpit_config,
    cockpit_store,
    nudge_engine,
    whatsapp_engine,
)

logger = logging.getLogger(__name__)

_DB = Path.home() / ".dev-bridge" / "wa_cockpit.db"
_CFG = Path.home() / ".dev-bridge" / "wa_cockpit_config.json"


async def _tick(db) -> None:
    cfg = cockpit_config.load(_CFG)
    # The poller has no panel binding of its own. Try one session per connected
    # Chrome profile until one reaches WhatsApp — the WA tab may live in any
    # profile. The extension's wa_store handler locates web.whatsapp.com by URL,
    # so the session's own bound tab is irrelevant.
    sessions = browser_relay.candidate_sessions()
    if not sessions:
        logger.debug("cockpit poll skipped: no connected browser session")
        return
    res = None
    session = None
    for candidate in sessions:
        try:
            res = await whatsapp_engine.list_chats(limit=200, session=candidate, quiet=True)
        except HTTPException as exc:
            logger.debug(
                "cockpit poll: list_chats failed on session=%s status=%s detail=%s",
                candidate,
                exc.status_code,
                exc.detail,
            )
            continue
        if not res.get("ok") and res.get("error") == "whatsapp_not_open":
            logger.debug("cockpit poll skipped: web.whatsapp.com not open in Chrome")
            return
        if res.get("ok"):
            session = candidate
            break
    if not session or not res or not res.get("ok"):
        logger.debug("cockpit poll skipped: WhatsApp tab not reachable from any profile")
        return
    for chat in res["data"]:
        in_scope = cockpit_config.is_in_scope(
            cfg, chat["id"], is_group=chat.get("isGroup", False)
        )
        cockpit_store.upsert_chat(db, chat, in_scope=in_scope)
        if in_scope:
            msgs = await whatsapp_engine.get_messages(
                chat["id"], limit=20, session=session, quiet=True,
            )
            if msgs.get("ok"):
                cockpit_store.upsert_messages(db, chat["id"], msgs["data"])
    chats = [dict(r) for r in cockpit_store.list_chats(db)]
    nudges = nudge_engine.compute(
        chats, now=int(time.time()), threshold_s=cfg["threshold_hours"] * 3600
    )
    _persist_nudges(db, nudges)


def _persist_nudges(db, nudges: list[dict]) -> None:
    open_ids = {n["chat_id"] for n in nudges}
    now_ts = int(time.time())
    for n in nudges:
        db.execute(
            """INSERT INTO nudges (chat_id, since_ts, state, notified, updated_at)
               VALUES (?, ?, 'open', 0, ?)
               ON CONFLICT(chat_id) DO UPDATE SET
                 since_ts=excluded.since_ts,
                 state=CASE WHEN nudges.state='handled' THEN 'open'
                            ELSE nudges.state END,
                 updated_at=excluded.updated_at""",
            (n["chat_id"], n["since_ts"], now_ts),
        )
    # Auto-clear nudges that are no longer open (user replied)
    if open_ids:
        placeholders = ",".join("?" * len(open_ids))
        db.execute(
            f"UPDATE nudges SET state='handled' WHERE state='open' "
            f"AND chat_id NOT IN ({placeholders})",
            tuple(open_ids),
        )
    else:
        db.execute("UPDATE nudges SET state='handled' WHERE state='open'")
    db.commit()


async def run_forever() -> None:
    """Run the cockpit poller loop indefinitely. Meant to be launched as a task."""
    db = cockpit_store.open_store(_DB)
    try:
        while True:
            interval = cockpit_config.load(_CFG).get("poll_interval_s", 300)
            try:
                await _tick(db)
            except Exception:  # noqa: BLE001 — loop must never die
                logger.exception("cockpit poll tick failed")
            await asyncio.sleep(interval)
    finally:
        db.close()
