"""Tests for WhatsApp cockpit inbox detection and filtering."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from devscope_bridge.whatsapp import cockpit_inbox


def test_is_inbox_query_hebrew():
    assert cockpit_inbox.is_inbox_query("יש הודעות חדשות?", None)
    assert not cockpit_inbox.is_inbox_query("מה כתב לי דני?", None)


def test_is_inbox_query_from_history():
    history = [{"role": "user", "content": "יש הודעות חדשות?"}]
    assert cockpit_inbox.is_inbox_query("לא בקבוצות", history)


def test_parse_filters_dms_only():
    f = cockpit_inbox.parse_filters("לא בקבוצות", None)
    assert f["dms_only"] is True
    assert f["groups_only"] is False


def test_parse_filters_from_history():
    history = [{"role": "user", "content": "יש הודעות חדשות?"}]
    f = cockpit_inbox.parse_filters("פרטיים בלבד", history)
    assert f["dms_only"] is True


def test_effective_question_merges_refinement():
    history = [{"role": "user", "content": "יש הודעות חדשות?"}]
    q = cockpit_inbox.effective_question("לא בקבוצות", history)
    assert "הודעות חדשות" in q
    assert "לא בקבוצות" in q


def test_should_use_inbox_overrides_scoped_chat():
    assert cockpit_inbox.should_use_inbox(
        "יש הודעות חדשות?", "123@g.us", None,
    )
    assert cockpit_inbox.should_use_inbox(
        "לא בקבוצות", "123@g.us",
        [{"role": "user", "content": "יש הודעות חדשות?"}],
    )


def test_filter_chats_dms_only():
    chats = [
        {"id": "1@c.us", "isGroup": False, "name": "Dan"},
        {"id": "2@g.us", "isGroup": True, "name": "Team"},
    ]
    out = cockpit_inbox._filter_chats(chats, dms_only=True, groups_only=False)
    assert len(out) == 1
    assert out[0]["name"] == "Dan"


def test_format_inbox_block_empty():
    block = cockpit_inbox.format_inbox_block(
        [], dms_only=True, groups_only=False, total_unread_before_filter=3,
    )
    assert "private chats" in block
    assert "No unread" in block


@pytest.mark.asyncio
async def test_fetch_unread_inbox_filters():
    mock_chats = {
        "ok": True,
        "data": [
            {"id": "1@c.us", "isGroup": False, "unreadCount": 2, "name": "A"},
            {"id": "2@g.us", "isGroup": True, "unreadCount": 5, "name": "G"},
        ],
    }
    with patch(
        "devscope_bridge.whatsapp.cockpit_inbox.cockpit_sync.pick_wa_session",
        new=AsyncMock(return_value="sess1"),
    ), patch(
        "devscope_bridge.whatsapp.cockpit_inbox.whatsapp_engine.list_chats",
        new=AsyncMock(return_value=mock_chats),
    ):
        chats, total, err = await cockpit_inbox.fetch_unread_inbox(
            "sess1", dms_only=True,
        )
    assert err is None
    assert total == 2
    assert len(chats) == 1
    assert chats[0]["id"] == "1@c.us"
