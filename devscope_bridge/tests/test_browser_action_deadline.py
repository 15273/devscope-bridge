"""
test_browser_action_deadline.py — every browser tool_call MUST resolve.

Real incident: an in-flight Browser·Screenshot call was orphaned when the
Chrome extension reloaded mid-action. The pending Future had no deadline and
WS disconnect did not touch `_pending_actions`, so the agent's turn hung
silently for 10+ minutes.

Two independent safety nets now guarantee resolution:
1. Per-action deadline (`browser_relay._action_timeout_s`) — `_send_action`
   resolves ok=False with a "timeout: ..." error if nothing answers in time.
2. Disconnect sweep (`browser_relay.fail_pending_for_session`) — triggered by
   `deregister_ws`, resolves every action dispatched over that session's WS
   with ok=False/"extension_disconnected" immediately, without waiting for
   the deadline.

A browser_result that arrives after either safety net already resolved the
action must be a safe no-op (no crash, no double-resolve).

Mirrors the idioms in test_actions_endpoint_resolves_on_browser_result.py
(FakeWebSocket + ASGI transport hitting /actions) and test_stuck_turn_handling.py
(monkeypatching the deadline constant to keep tests fast).
"""

import asyncio
import json

import pytest
from httpx import AsyncClient, ASGITransport

from devscope_bridge.main import app
from devscope_bridge.models import BrowserResult
from devscope_bridge import browser_relay


class _SilentWebSocket:
    """Accepts the tool_call frame but never sends back a browser_result."""

    def __init__(self) -> None:
        self.sent_frames: list[dict] = []

    async def send_text(self, text: str) -> None:
        self.sent_frames.append(json.loads(text))


class _EchoingWebSocket:
    """Immediately resolves any dispatched action with ok=True (happy path)."""

    def __init__(self) -> None:
        self.sent_frames: list[dict] = []

    async def send_text(self, text: str) -> None:
        frame = json.loads(text)
        self.sent_frames.append(frame)
        if frame.get("type") == "tool_call":
            action_id = frame["action_id"]
            asyncio.get_event_loop().call_soon(
                _resolve, action_id,
                {"type": "browser_result", "action_id": action_id,
                 "ok": True, "data": {"ok": "yes"}, "error": None},
            )


def _resolve(action_id: str, result_dict: dict) -> None:
    future = browser_relay._pending_actions.get(action_id)
    if future and not future.done():
        future.set_result(BrowserResult(**result_dict))


# ─────────────────────────────────────────────
# Per-tool deadline map
# ─────────────────────────────────────────────

def test_action_timeout_defaults_to_60s_for_unlisted_tools():
    assert browser_relay._action_timeout_s("browser_click") == (
        browser_relay._DEFAULT_ACTION_TIMEOUT_S
    )
    assert browser_relay._DEFAULT_ACTION_TIMEOUT_S == 60.0


def test_action_timeout_overrides_screenshot_and_snapshot_to_30s():
    assert browser_relay._action_timeout_s("browser_screenshot") == 30.0
    assert browser_relay._action_timeout_s("browser_snapshot") == 30.0


# ─────────────────────────────────────────────
# 1. Timeout → resolves ok=False, never hangs
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_action_times_out_resolves_ok_false(monkeypatch):
    """No browser_result ever arrives — the deadline must resolve the call,
    not hang. Deadline is monkeypatched to a few ms so the test runs fast."""
    monkeypatch.setattr(browser_relay, "_DEFAULT_ACTION_TIMEOUT_S", 0.05)
    fake_ws = _SilentWebSocket()
    browser_relay._active_ws["deadline-sess"] = fake_ws

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        resp = await asyncio.wait_for(
            client.post(
                "/actions",
                json={"tool": "browser_get_page_info", "args": {}, "session": "deadline-sess"},
                headers={"Authorization": "Bearer test-token-abc123"},
                timeout=5.0,
            ),
            timeout=2.0,  # proves the request itself does not hang
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert "timeout" in body["error"].lower()
    assert "0" in body["error"]  # deadline value is echoed back

    # Bookkeeping must not leak.
    assert browser_relay._pending_actions == {}
    assert browser_relay._action_session == {}


# ─────────────────────────────────────────────
# 2. WS disconnect → resolves immediately, does not wait for the deadline
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ws_disconnect_resolves_pending_action_immediately(monkeypatch):
    """A generous deadline is set so that only the disconnect sweep — not the
    deadline — could plausibly resolve the action within the test's window."""
    monkeypatch.setattr(browser_relay, "_DEFAULT_ACTION_TIMEOUT_S", 5.0)
    ws = _SilentWebSocket()
    browser_relay._active_ws["disc-sess"] = ws

    task = asyncio.create_task(
        browser_relay._send_action("disc-sess", "browser_click", {"selector": "#x"})
    )
    # Let _send_action register the pending action before we disconnect.
    for _ in range(50):
        if browser_relay._pending_actions:
            break
        await asyncio.sleep(0.01)

    browser_relay.deregister_ws("disc-sess", ws)

    result = await asyncio.wait_for(task, timeout=1.0)  # << well under the 5s deadline
    assert result.ok is False
    assert result.error == "extension_disconnected"
    assert browser_relay._pending_actions == {}
    assert browser_relay._action_session == {}


# ─────────────────────────────────────────────
# 3. Late browser_result after resolution is ignored, never crashes
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_late_result_after_timeout_is_ignored(monkeypatch):
    monkeypatch.setattr(browser_relay, "_DEFAULT_ACTION_TIMEOUT_S", 0.05)

    captured: dict[str, str] = {}

    class _CapturingWebSocket:
        async def send_text(self, text: str) -> None:
            captured["action_id"] = json.loads(text)["action_id"]

    browser_relay._active_ws["late-sess"] = _CapturingWebSocket()

    result = await browser_relay._send_action("late-sess", "browser_click", {"selector": "#x"})
    assert result.ok is False
    assert "timeout" in result.error.lower()
    assert "action_id" in captured

    # The action_id was already popped by _send_action's finally block, so
    # this lands in the "unknown action_id" branch — must not raise.
    browser_relay.resolve_browser_result({
        "type": "browser_result", "action_id": captured["action_id"],
        "ok": True, "data": {"too": "late"}, "error": None,
    })


@pytest.mark.asyncio
async def test_late_result_for_already_done_future_is_ignored():
    """Covers the future.done() branch directly: the Future is still present
    in _pending_actions (not yet cleaned up) but already resolved — a second
    browser_result for it must not double-resolve or raise."""
    future: asyncio.Future = asyncio.get_event_loop().create_future()
    future.set_result(
        BrowserResult(action_id="dup-action", ok=True, data={"first": True}, error=None)
    )
    browser_relay._pending_actions["dup-action"] = future

    browser_relay.resolve_browser_result({
        "type": "browser_result", "action_id": "dup-action",
        "ok": False, "data": None, "error": "should be ignored",
    })

    # Original result must be untouched.
    assert future.result().data == {"first": True}


# ─────────────────────────────────────────────
# 4. Normal resolve path still works
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_normal_resolve_path_still_works():
    """Sanity check: the deadline/sweep machinery must not interfere with a
    browser_result that arrives promptly. (Mirrors
    test_actions_endpoint_resolves_on_browser_result.py.)"""
    fake_ws = _EchoingWebSocket()
    browser_relay._active_ws["happy-sess"] = fake_ws

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        resp = await client.post(
            "/actions",
            json={"tool": "browser_get_page_info", "args": {}, "session": "happy-sess"},
            headers={"Authorization": "Bearer test-token-abc123"},
            timeout=5.0,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"] == {"ok": "yes"}
    assert browser_relay._pending_actions == {}
    assert browser_relay._action_session == {}
