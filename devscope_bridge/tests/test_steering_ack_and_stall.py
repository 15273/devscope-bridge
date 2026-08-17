"""
test_steering_ack_and_stall.py — A8 (RC-7) + contract 1: msg_ack / perm_ack,
queued_turns bookkeeping, and the "steering message may have been dropped"
watchdog warning.

Coverage
--------
1. A user_msg WITH client_msg_id gets a msg_ack reply on the same WS.
2. A user_msg WITHOUT client_msg_id (old panel build) gets no ack — pure
   backwards compatibility, never breaks old clients.
3. A permission_response always gets a perm_ack after send_approval.
4. session_manager.run_prompt increments pending_prompts when writing mid-turn
   (turn_done not yet set) and does NOT increment when idle.
5. session_reader's decrement (invoked from continuous_reader when a new
   turn's first stdout event arrives) brings it back down.
6. Simulated result-with-pending-prompt and no follow-up turn -> the
   steering-stall watchdog check fires the warning activity (the plan's exact
   Test line for A8).
"""

import asyncio
import json
import pytest
from fastapi import WebSocketDisconnect

import devscope_bridge.main as bridge_main
import devscope_bridge.session_manager as mgr
import devscope_bridge.session_reader as sr
import devscope_bridge.session_store as store
from devscope_bridge.models import AgentActivity


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "SESSIONS_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(store, "BRIDGE_DIR", tmp_path)
    mgr._sessions.clear()
    yield
    mgr._sessions.clear()


class _ScriptedWS:
    """Replays a fixed list of inbound frames, then disconnects; records sends."""

    def __init__(self, frames: list[str]):
        self._frames = frames
        self._i = 0
        self.sent: list[str] = []

    async def receive_text(self) -> str:
        if self._i < len(self._frames):
            f = self._frames[self._i]
            self._i += 1
            return f
        raise WebSocketDisconnect(code=1000)

    async def send_text(self, text: str) -> None:
        self.sent.append(text)


# ─────────────────────────────────────────────
# 1–2. msg_ack contract 1 (backward compatible)
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_user_msg_with_client_msg_id_gets_msg_ack(monkeypatch):
    async def fake_run_prompt(name, prompt, mode=None, model=None, context=None):
        return asyncio.Queue()

    monkeypatch.setattr(mgr, "run_prompt", fake_run_prompt)
    monkeypatch.setattr(mgr, "reset_idle", lambda n: None)

    ws = _ScriptedWS([json.dumps({
        "type": "user_msg", "text": "hello", "client_msg_id": "cmid-1",
    })])
    await bridge_main._ws_receive_loop(ws, "ack-sess")

    acks = [json.loads(s) for s in ws.sent if json.loads(s).get("type") == "msg_ack"]
    assert len(acks) == 1
    assert acks[0]["client_msg_id"] == "cmid-1"


@pytest.mark.asyncio
async def test_user_msg_without_client_msg_id_gets_no_ack(monkeypatch):
    """Old panel builds (no client_msg_id field) must keep working unacked."""
    async def fake_run_prompt(name, prompt, mode=None, model=None, context=None):
        return asyncio.Queue()

    monkeypatch.setattr(mgr, "run_prompt", fake_run_prompt)
    monkeypatch.setattr(mgr, "reset_idle", lambda n: None)

    ws = _ScriptedWS([json.dumps({"type": "user_msg", "text": "hello"})])
    await bridge_main._ws_receive_loop(ws, "noack-sess")

    acks = [json.loads(s) for s in ws.sent if json.loads(s).get("type") == "msg_ack"]
    assert acks == []


# ─────────────────────────────────────────────
# 3. perm_ack contract 1
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_permission_response_gets_perm_ack(monkeypatch):
    async def fake_send_approval(name, request_id, option_id, **kwargs):
        return True

    monkeypatch.setattr(mgr, "send_approval", fake_send_approval)

    ws = _ScriptedWS([json.dumps({
        "type": "permission_response", "request_id": "req-77", "option_id": "approve",
    })])
    await bridge_main._ws_receive_loop(ws, "perm-sess")

    acks = [json.loads(s) for s in ws.sent if json.loads(s).get("type") == "perm_ack"]
    assert len(acks) == 1
    assert acks[0]["request_id"] == "req-77"


# ─────────────────────────────────────────────
# 4–5. pending_prompts (queued_turns) bookkeeping
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_prompt_increments_pending_prompts_only_mid_turn(monkeypatch):
    class _FakeStdin:
        def write(self, b):
            pass

        async def drain(self):
            return None

    class _FakeProc:
        pid = 555
        returncode = None
        stdin = _FakeStdin()

    async def fake_spawn(*args, **kwargs):
        return _FakeProc()

    async def fake_reader(*args, **kwargs):
        await asyncio.sleep(999)

    monkeypatch.setattr(mgr, "_spawn_claude_proc", fake_spawn)
    monkeypatch.setattr(mgr.session_reader, "continuous_reader", fake_reader)

    await mgr.run_prompt("steer-sess", "first message")
    active = mgr._sessions["steer-sess"]
    assert active.pending_prompts == 0, "First message (session idle) is not steering"

    # Turn is now running (turn_done cleared by the first call) — a SECOND
    # message written before the turn ends is steering.
    await mgr.run_prompt("steer-sess", "second message mid-turn")
    assert active.pending_prompts == 1


def test_decrement_pending_prompts_floors_at_zero():
    mgr.decrement_pending_prompts("no-such-session")  # must not raise

    store.create_session_metadata("dec-sess", "claude", store.DEFAULT_CWD)

    class _FakeProc:
        pid = 1
        returncode = None

    active = mgr._ActiveSession(
        name="dec-sess", session_id="sid", proc=_FakeProc(),
        out_queue=asyncio.Queue(), reader_task=None, idle_task=None,
        mode=None, model=None, turn_done=asyncio.Event(),
        pending_prompts=1,
    )
    mgr._sessions["dec-sess"] = active
    mgr.decrement_pending_prompts("dec-sess")
    assert active.pending_prompts == 0
    mgr.decrement_pending_prompts("dec-sess")  # floors at zero, no negative
    assert active.pending_prompts == 0


# ─────────────────────────────────────────────
# 6. Steering-stall watchdog warning (A8's exact plan Test line)
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_steering_stall_warns_when_no_follow_up_turn(monkeypatch):
    """Simulate result-with-pending-prompt and no follow-up turn -> warning fires."""
    monkeypatch.setattr(sr, "_STEERING_STALL_S", 0.1)
    monkeypatch.setattr(sr, "_WATCHDOG_HEARTBEAT_S", 0.05)  # keeps the loop's tick small
    monkeypatch.setattr(sr, "_WATCHDOG_HARD_CAP_S", 999)

    q: asyncio.Queue = asyncio.Queue()
    activity_event = asyncio.Event()
    turn_active = asyncio.Event()  # starts CLEAR — session is idle

    pending_count = [1]  # one steering message written, no new turn ever starts

    watchdog = asyncio.create_task(sr._watchdog_loop(
        "stall-sess", q, activity_event,
        turn_active_event=turn_active,
        pending_prompts_fn=lambda: pending_count[0],
    ))

    await asyncio.sleep(0.35)
    watchdog.cancel()
    try:
        await watchdog
    except asyncio.CancelledError:
        pass

    frames = []
    while not q.empty():
        frames.append(q.get_nowait())

    warnings = [
        f for f in frames
        if isinstance(f, AgentActivity) and f.status == "error"
        and "dropped" in (f.label + (f.detail or "")).lower()
    ]
    assert len(warnings) == 1, f"Expected exactly one steering-stall warning: {frames}"


@pytest.mark.asyncio
async def test_no_steering_stall_warning_once_new_turn_starts(monkeypatch):
    """If a new turn starts (pending_prompts_fn drops to 0), no warning fires."""
    monkeypatch.setattr(sr, "_STEERING_STALL_S", 0.1)
    monkeypatch.setattr(sr, "_WATCHDOG_HEARTBEAT_S", 0.05)  # keeps the loop's tick small
    monkeypatch.setattr(sr, "_WATCHDOG_HARD_CAP_S", 999)

    q: asyncio.Queue = asyncio.Queue()
    activity_event = asyncio.Event()
    turn_active = asyncio.Event()
    pending_count = [1]

    watchdog = asyncio.create_task(sr._watchdog_loop(
        "no-stall-sess", q, activity_event,
        turn_active_event=turn_active,
        pending_prompts_fn=lambda: pending_count[0],
    ))

    await asyncio.sleep(0.05)
    pending_count[0] = 0  # the CLI picked it up as a new turn

    await asyncio.sleep(0.3)
    watchdog.cancel()
    try:
        await watchdog
    except asyncio.CancelledError:
        pass

    frames = []
    while not q.empty():
        frames.append(q.get_nowait())
    warnings = [f for f in frames if isinstance(f, AgentActivity) and f.status == "error"]
    assert warnings == []
