"""Tests for cockpit_sync live hydration helpers."""

from __future__ import annotations

import sqlite3
import time
from unittest.mock import AsyncMock, patch

import pytest

from devscope_bridge.whatsapp import cockpit_config, cockpit_store, cockpit_sync


def test_messages_from_rows_oldest_first():
    rows = [
        {"id": "m2", "text": "second", "from_me": 0, "author": "x", "ts": 200},
        {"id": "m1", "text": "first", "from_me": 1, "author": "me", "ts": 100},
    ]
    out = cockpit_sync.messages_from_rows(rows)
    assert [m["text"] for m in out] == ["first", "second"]
    assert out[0]["from_me"] is True


def test_mirror_is_stale_when_empty(tmp_path):
    db = cockpit_store.open_store(tmp_path / "wa.db")
    assert cockpit_sync._mirror_is_stale(db, "1@c.us") is True
    db.close()


def test_mirror_is_stale_when_old(tmp_path):
    db = cockpit_store.open_store(tmp_path / "wa.db")
    old_ts = int(time.time()) - cockpit_sync._STALE_S - 10
    cockpit_store.upsert_messages(db, "1@c.us", [
        {"id": "m1", "author": "1@c.us", "text": "hi", "ts": old_ts,
         "fromMe": False, "type": "chat"},
    ])
    assert cockpit_sync._mirror_is_stale(db, "1@c.us") is True
    db.close()


@pytest.mark.asyncio
async def test_hydrate_uses_mirror_when_fresh(tmp_path):
    db = cockpit_store.open_store(tmp_path / "wa.db")
    cfg = {**cockpit_config.DEFAULT}
    recent_ts = int(time.time()) - 60
    cockpit_store.upsert_chat(db, {
        "id": "1@c.us", "name": "Dana", "isGroup": False,
        "lastMessage": {"preview": "hi", "ts": recent_ts, "fromMe": False},
    }, in_scope=True)
    cockpit_store.upsert_messages(db, "1@c.us", [
        {"id": "m1", "author": "1@c.us", "text": "hello", "ts": recent_ts,
         "fromMe": False, "type": "chat"},
    ])

    with patch.object(cockpit_sync, "pick_wa_session", AsyncMock(return_value="sess")):
        with patch("devscope_bridge.whatsapp.whatsapp_engine.get_messages") as get_msgs:
            msgs, err = await cockpit_sync.hydrate_chat_messages(
                db, "1@c.us", "sess", cfg, limit=10,
            )
            get_msgs.assert_not_called()

    assert err is None
    assert msgs[0]["text"] == "hello"
    db.close()


@pytest.mark.asyncio
async def test_hydrate_fetches_live_when_empty(tmp_path):
    db = cockpit_store.open_store(tmp_path / "wa.db")
    cfg = {**cockpit_config.DEFAULT}
    cockpit_store.upsert_chat(db, {
        "id": "1@c.us", "name": "Dana", "isGroup": False,
        "lastMessage": {"preview": "hi", "ts": 100, "fromMe": False},
    }, in_scope=True)

    live_msgs = [
        {"id": "m1", "author": "1@c.us", "text": "live", "ts": int(time.time()),
         "fromMe": False, "type": "chat"},
    ]

    with patch.object(cockpit_sync, "pick_wa_session", AsyncMock(return_value="sess")):
        with patch(
            "devscope_bridge.whatsapp.whatsapp_engine.get_messages",
            AsyncMock(return_value={"ok": True, "data": live_msgs}),
        ):
            msgs, err = await cockpit_sync.hydrate_chat_messages(
                db, "1@c.us", "sess", cfg, limit=10, force=True,
            )

    assert err is None
    assert msgs[0]["text"] == "live"
    db.close()
