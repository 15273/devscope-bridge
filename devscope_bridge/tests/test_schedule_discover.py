"""Tests for schedule discover JSON parsing and API route."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from devscope_bridge.schedule_discover import discover_playbook, extract_json_object


def test_extract_json_object_raw():
    data = extract_json_object('{"playbook": {"site": "x.com"}, "instruction": "go"}')
    assert data["playbook"]["site"] == "x.com"


def test_extract_json_object_fenced():
    text = 'Here:\n```json\n{"playbook": {"workflow": ["a"]}, "instruction": "b"}\n```'
    data = extract_json_object(text)
    assert data["playbook"]["workflow"] == ["a"]


def test_extract_json_object_with_prefix():
    text = 'Analysis done.\n{"playbook": {"site": "linkedin.com"}, "instruction": "post"}'
    data = extract_json_object(text)
    assert data["playbook"]["site"] == "linkedin.com"


@pytest.mark.asyncio
async def test_discover_playbook_no_session():
    with patch(
        "devscope_bridge.schedule_discover.pick_browser_session",
        AsyncMock(return_value=None),
    ):
        result = await discover_playbook(entry_url="https://example.com", goal="test")
    assert result["ok"] is False
    assert "session" in result["error"]


@pytest.mark.asyncio
async def test_discover_playbook_parses_agent_json():
    claude_out = (
        '{"playbook": {"site": "linkedin.com", "workflow": ["open feed"], '
        '"selectors": {"composer": ".ql-editor"}}, "instruction": "Post weekly"}'
    )

    with patch(
        "devscope_bridge.schedule_discover.pick_browser_session",
        AsyncMock(return_value="my-session"),
    ):
        with patch(
            "devscope_bridge.whatsapp.cockpit_agent.run",
            AsyncMock(return_value=claude_out),
        ):
            result = await discover_playbook(
                entry_url="https://linkedin.com/feed/",
                goal="Weekly post",
                session_name="my-session",
                agent="cursor",
            )

    assert result["ok"] is True
    assert result["playbook"]["selectors"]["composer"] == ".ql-editor"
