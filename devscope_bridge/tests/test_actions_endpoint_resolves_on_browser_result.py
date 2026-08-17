"""
Test that POST /actions resolves correctly when the extension sends back
a matching browser_result frame over the WebSocket.

Rather than spinning up a real WS connection (which conflicts with the
lifespan token generation), we inject a mock WebSocket directly into
_active_ws and simulate the browser_result delivery.
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient, ASGITransport

from devscope_bridge.main import app
import devscope_bridge.browser_relay as bridge_relay


class _FakeWebSocket:
    """
    Minimal mock that captures what the bridge sends, and allows the test
    to simulate a browser_result coming back.
    """

    def __init__(self):
        self.sent_frames: list[dict] = []

    async def send_text(self, text: str) -> None:
        frame = json.loads(text)
        self.sent_frames.append(frame)
        # When the bridge sends a tool_call frame, immediately resolve the
        # pending future as if the extension echoed back a browser_result.
        if frame.get("type") == "tool_call":
            action_id = frame["action_id"]
            asyncio.get_event_loop().call_soon(
                _resolve_pending,
                action_id,
                {"type": "browser_result", "action_id": action_id,
                 "ok": True,
                 "data": {"url": "https://example.com", "title": "Example",
                          "viewport": {}, "scroll": {}},
                 "error": None},
            )


class _FakeWebSocketError:
    """Returns ok=False with an error message."""

    def __init__(self):
        self.sent_frames: list[dict] = []

    async def send_text(self, text: str) -> None:
        frame = json.loads(text)
        self.sent_frames.append(frame)
        if frame.get("type") == "tool_call":
            action_id = frame["action_id"]
            asyncio.get_event_loop().call_soon(
                _resolve_pending,
                action_id,
                {"type": "browser_result", "action_id": action_id,
                 "ok": False,
                 "data": None,
                 "error": "Element not found"},
            )


def _resolve_pending(action_id: str, result_dict: dict) -> None:
    """Resolve the Future stored in _pending_actions for action_id."""
    from devscope_bridge.models import BrowserResult
    future = bridge_relay._pending_actions.get(action_id)
    if future and not future.done():
        future.set_result(BrowserResult(**result_dict))


@pytest.mark.asyncio
async def test_resolves_on_browser_result():
    """
    Injects a fake WS that auto-resolves with ok=True data.
    POST /actions should return {ok: true, data: {...}}.
    """
    fake_ws = _FakeWebSocket()
    bridge_relay._active_ws["test-session"] = fake_ws

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        resp = await client.post(
            "/actions",
            json={"tool": "browser_get_page_info", "args": {}, "session": "test-session"},
            headers={"Authorization": "Bearer test-token-abc123"},
            timeout=5.0,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["title"] == "Example"

    assert len(fake_ws.sent_frames) == 1
    assert fake_ws.sent_frames[0]["type"] == "tool_call"
    assert fake_ws.sent_frames[0]["tool"] == "browser_get_page_info"


@pytest.mark.asyncio
async def test_resolves_with_error_result():
    """Extension sends ok=False — the HTTP response should reflect that."""
    fake_ws = _FakeWebSocketError()
    bridge_relay._active_ws["test-session-err"] = fake_ws

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        resp = await client.post(
            "/actions",
            json={"tool": "browser_click", "args": {"selector": "#missing"},
                  "session": "test-session-err"},
            headers={"Authorization": "Bearer test-token-abc123"},
            timeout=5.0,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["error"] == "Element not found"


@pytest.mark.asyncio
async def test_unknown_action_id_dropped():
    """
    A browser_result with an unknown action_id should be silently dropped
    (no crash, no KeyError).
    """
    from devscope_bridge.browser_relay import resolve_browser_result
    resolve_browser_result({"type": "browser_result", "action_id": "does-not-exist",
                            "ok": True, "data": None, "error": None})
    # If no exception, the test passes
