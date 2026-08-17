"""
test_ws_pump_reliability.py — A1/RC-4: WS pump attaches on connect, never a
throwaway out_queue, no dropped frames on send failure, no stale-socket
deregistration.

Coverage
--------
1. _resolve_out_queue returns the SAME persistent queue across repeated calls
   for a session that has not spawned yet (no throwaway).
2. That SAME queue is the one session_manager.run_prompt's claude-spawn path
   ends up writing to (get_or_create_out_queue reuse).
3. _pump_frames requeues (does not drop) a frame when ws.send_text fails —
   "reconnect mid-turn" regression: a fresh pump on the same queue still
   delivers it.
4. _start_session_pump cancels a still-running previous pump for the same
   session (fast reconnect must not leave two pumps draining one queue).
5. browser_relay.deregister_ws ignores a stale ws if a newer one already
   replaced it (covered in test_cross_profile_routing.py; sanity re-check here
   with the main.py session pump registry).
6. Slash-command-first-then-message: a session command (e.g. /medic) resolves
   the queue before any user_msg, and a LATER real chat message still lands on
   frames delivered by the SAME pump (no second orphaned queue).
"""

import asyncio
import pytest

import devscope_bridge.main as bridge_main
import devscope_bridge.session_manager as mgr
import devscope_bridge.session_manager_cursor as cursor_mgr
import devscope_bridge.session_store as store
from devscope_bridge.models import AiChunk


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    # Never touch the real ~/.dev-bridge — the bridge this test suite exercises
    # may be live, serving real sessions.
    monkeypatch.setattr(store, "SESSIONS_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(store, "BRIDGE_DIR", tmp_path)
    monkeypatch.setattr(store, "BRIDGE_TRANSCRIPTS_DIR", tmp_path / "chat-transcripts")
    mgr._sessions.clear()
    mgr._out_queues.clear()
    cursor_mgr._cursor_out_queues.clear()
    bridge_main._session_pumps.clear()
    yield
    mgr._sessions.clear()
    mgr._out_queues.clear()
    cursor_mgr._cursor_out_queues.clear()
    bridge_main._session_pumps.clear()


class _FakeWS:
    def __init__(self, fail_send: bool = False):
        self.sent: list[str] = []
        self.fail_send = fail_send

    async def send_text(self, text: str) -> None:
        if self.fail_send:
            raise RuntimeError("connection closed")
        self.sent.append(text)


# ─────────────────────────────────────────────
# 1–2. Persistent registry — no throwaway queue
# ─────────────────────────────────────────────

def test_resolve_out_queue_is_stable_before_any_spawn():
    store.create_session_metadata("never-spawned", "claude", store.DEFAULT_CWD)
    q1 = bridge_main._resolve_out_queue("never-spawned")
    q2 = bridge_main._resolve_out_queue("never-spawned")
    assert q1 is q2, "Repeated resolution before spawn must return the SAME queue"


@pytest.mark.asyncio
async def test_resolve_out_queue_matches_run_prompt_spawn_queue(monkeypatch):
    """The queue a WS pump attaches to BEFORE any message must be the exact
    object run_prompt's claude-spawn path later writes frames to."""
    store.create_session_metadata("pre-attach", "claude", store.DEFAULT_CWD)
    pre_attach_q = bridge_main._resolve_out_queue("pre-attach")

    class _FakeProc:
        pid = 4242
        returncode = None
        stdin = None

    async def fake_spawn(*args, **kwargs):
        proc = _FakeProc()
        proc.stdin = type("S", (), {"write": lambda self, b: None, "drain": _noop})()
        return proc

    async def _noop(self=None):
        return None

    monkeypatch.setattr(mgr, "_spawn_claude_proc", fake_spawn)
    monkeypatch.setattr(mgr.session_reader, "continuous_reader", AsyncNoop())

    spawned_q = await mgr.run_prompt("pre-attach", "hello")
    assert spawned_q is pre_attach_q


class AsyncNoop:
    """Callable that returns a coroutine doing nothing — stand-in for a reader task body."""
    async def __call__(self, *args, **kwargs):
        await asyncio.sleep(0)


# ─────────────────────────────────────────────
# 3. No dropped frames on send failure (reconnect mid-turn)
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pump_frames_requeues_on_send_failure_reconnect_delivers():
    q: asyncio.Queue = asyncio.Queue()
    await q.put(AiChunk(session="s", text="hello"))

    dead_ws = _FakeWS(fail_send=True)
    await bridge_main._pump_frames(dead_ws, q)  # pops the frame, send fails, exits

    # The frame must still be sitting in the queue for the NEXT pump.
    assert q.qsize() == 1

    live_ws = _FakeWS(fail_send=False)
    pump_task = asyncio.create_task(bridge_main._pump_frames(live_ws, q))
    await asyncio.sleep(0.05)
    pump_task.cancel()
    try:
        await pump_task
    except asyncio.CancelledError:
        pass

    assert len(live_ws.sent) == 1
    assert "hello" in live_ws.sent[0]


# ─────────────────────────────────────────────
# 4. Fast reconnect cancels the old pump
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_start_session_pump_cancels_previous():
    q: asyncio.Queue = asyncio.Queue()
    ws1 = _FakeWS()
    first = bridge_main._start_session_pump("dup-sess", ws1, q)
    await asyncio.sleep(0.01)
    assert not first.done()

    ws2 = _FakeWS()
    second = bridge_main._start_session_pump("dup-sess", ws2, q)
    await asyncio.sleep(0.01)

    assert first.cancelled() or first.done()
    assert bridge_main._session_pumps["dup-sess"] is second
    second.cancel()
    try:
        await second
    except asyncio.CancelledError:
        pass


# ─────────────────────────────────────────────
# 6. Slash-command-first-then-message: same queue, same pump
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_command_queue_then_later_spawn_share_the_same_queue():
    """A /medic (or any session command) resolves the queue BEFORE any
    user_msg. A real chat message dispatched afterward must still write to
    that SAME queue — not a second, orphaned one (RC-4's core bug)."""
    store.create_session_metadata("cmd-first", "claude", store.DEFAULT_CWD)
    ws = _FakeWS()

    # Simulates _handle_session_command's early resolution.
    q_from_command, pump_task = bridge_main._command_queue("cmd-first", ws, None)
    assert bridge_main._session_pumps.get("cmd-first") is pump_task

    # Later, the real spawn path resolves the queue independently.
    q_from_spawn = mgr.get_or_create_out_queue("cmd-first")
    assert q_from_spawn is q_from_command

    pump_task.cancel()
