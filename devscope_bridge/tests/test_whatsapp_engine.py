# test_whatsapp_engine.py
import pytest
from unittest.mock import AsyncMock, patch
from devscope_bridge.whatsapp import whatsapp_engine


@pytest.mark.asyncio
async def test_list_chats_forwards_to_relay_and_normalizes():
    fake = {"ok": True, "data": [{"id": "1@c.us", "name": "Dana", "unreadCount": 2}], "error": None}
    with patch.object(whatsapp_engine, "_wa_store_action", AsyncMock(return_value=fake)):
        out = await whatsapp_engine.list_chats(filter="unread", limit=10)
    assert out["ok"] is True
    assert out["data"][0]["name"] == "Dana"


@pytest.mark.asyncio
async def test_store_unavailable_surfaces_typed_error():
    fake = {"ok": False, "data": None, "error": "store_unavailable"}
    with patch.object(whatsapp_engine, "_wa_store_action", AsyncMock(return_value=fake)):
        out = await whatsapp_engine.list_chats()
    assert out["ok"] is False
    assert out["error"] == "store_unavailable"


@pytest.mark.asyncio
async def test_quiet_flag_forwarded_to_action_request():
    with patch("devscope_bridge.whatsapp.whatsapp_engine.browser_relay.post_action", AsyncMock(return_value={"ok": True})) as post:
        await whatsapp_engine.list_chats(quiet=True)
    body = post.call_args[0][0]
    assert body.quiet is True
