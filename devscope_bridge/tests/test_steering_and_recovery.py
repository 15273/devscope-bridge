"""
test_steering_and_recovery.py

Tests for the three new behaviours introduced in the pump/steering rework:

1. STEERING: Two messages sent without waiting for the first to finish both
   reach stdin (written immediately) and both turns' frames are forwarded by
   the pump. The pump does NOT break on the first AiDone.

2. STOP RECOVERY: interrupt_session() sends SIGINT and, when the process does
   not emit a result within _INTERRUPT_GRACE_S, force-emits AiError onto the
   queue and respawns the process so the UI unblocks.

3. QUEUE REUSE: When run_prompt() respawns (mode change), it reuses the
   existing out_queue — the reference returned on the first call is the same
   object returned on the second call and after respawn.

4. PUMP FORWARDS AIDONE WITHOUT STOPPING: The pump task keeps running after
   forwarding an AiDone frame (it only stops when cancelled).

5. ERROR SUBTYPE HANDLING: result events with is_error=True or subtype
   "error_max_turns" emit AiError, not AiDone.
"""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import devscope_bridge.session_store as store
import devscope_bridge.session_manager as mgr
from devscope_bridge.models import AiChunk, AiDone, AiError, SessionReady
from devscope_bridge import session_reader


# ─────────────────────────────────────────────
# Shared fixtures
# ─────────────────────────────────────────────

@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "SESSIONS_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(store, "BRIDGE_DIR", tmp_path)
    mgr._sessions.clear()
    yield
    mgr._sessions.clear()


class _ControlledAsyncIterator:
    """Async iterator whose items are fed via an asyncio.Queue.

    Yields items as they arrive; StopAsyncIteration when a sentinel None is put.
    """

    def __init__(self):
        self._q: asyncio.Queue = asyncio.Queue()

    def __aiter__(self):
        return self

    async def __anext__(self):
        item = await self._q.get()
        if item is None:
            raise StopAsyncIteration
        return item

    def push(self, line: str) -> None:
        self._q.put_nowait((line + "\n").encode("utf-8"))

    def close(self) -> None:
        self._q.put_nowait(None)


def _make_proc_with_controlled_stdout():
    proc = MagicMock()
    proc.pid = 11111
    proc.returncode = None
    ctrl = _ControlledAsyncIterator()
    proc.stdout = ctrl
    proc.stderr = AsyncMock()
    proc.stderr.read = AsyncMock(return_value=b"")
    proc.stdin = MagicMock()
    proc.stdin.write = MagicMock()
    proc.stdin.drain = AsyncMock()

    async def _wait():
        return 0
    proc.wait = _wait
    return proc, ctrl


def _init_evt(sid="s1"):
    return json.dumps({"type": "system", "subtype": "init", "session_id": sid})


def _chunk_evt(text, sid="s1"):
    return json.dumps({
        "type": "stream_event", "session_id": sid,
        "event": {"type": "content_block_delta", "index": 0,
                  "delta": {"type": "text_delta", "text": text}},
    })


def _result_evt(result="ok", sid="s1", is_error=False, subtype="success"):
    return json.dumps({
        "type": "result", "subtype": subtype,
        "is_error": is_error, "result": result, "session_id": sid,
    })


async def _collect_until_done(q, timeout=3.0) -> list:
    """Collect frames until AiDone or AiError, with timeout."""
    frames = []
    try:
        async with asyncio.timeout(timeout):
            while True:
                f = await q.get()
                frames.append(f)
                if isinstance(f, (AiDone, AiError)):
                    break
    except TimeoutError:
        pass
    return frames


# ─────────────────────────────────────────────
# Test 1: Steering — two messages reach stdin without waiting
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_steering_both_messages_reach_stdin():
    """MSG2 is written to stdin immediately without waiting for MSG1 to finish."""
    proc, ctrl = _make_proc_with_controlled_stdout()

    async def fake_spawn(*args, **kwargs):
        return proc

    with patch("devscope_bridge.session_manager.asyncio.create_subprocess_exec",
               side_effect=fake_spawn):
        # Send MSG1 — run_prompt writes to stdin and returns the queue
        q = await mgr.run_prompt("steer-sess", "MSG1")
        assert proc.stdin.write.call_count == 1

        # Send MSG2 immediately — no await for MSG1's turn to finish
        q2 = await mgr.run_prompt("steer-sess", "MSG2")
        assert proc.stdin.write.call_count == 2

    # Both return the same queue (stable)
    assert q is q2

    # Verify the payloads written to stdin
    calls = proc.stdin.write.call_args_list
    payload1 = json.loads(calls[0][0][0].decode().strip())
    payload2 = json.loads(calls[1][0][0].decode().strip())
    assert payload1["message"]["content"][0]["text"] == "MSG1"
    assert payload2["message"]["content"][0]["text"] == "MSG2"


@pytest.mark.asyncio
async def test_pump_forwards_both_turns_without_breaking():
    """Pump forwards Turn1 frames (including AiDone) then continues for Turn2."""
    proc, ctrl = _make_proc_with_controlled_stdout()

    async def fake_spawn(*args, **kwargs):
        return proc

    with patch("devscope_bridge.session_manager.asyncio.create_subprocess_exec",
               side_effect=fake_spawn):
        q = await mgr.run_prompt("pump-sess", "MSG1")

    # Feed Turn 1 events
    ctrl.push(_init_evt())
    ctrl.push(_chunk_evt("Hello"))
    ctrl.push(_result_evt("Hello"))

    # Wait for AiDone from Turn 1
    t1_frames = await _collect_until_done(q, timeout=3.0)
    assert any(isinstance(f, AiDone) for f in t1_frames), f"No AiDone in T1: {t1_frames}"
    t1_chunks = [f for f in t1_frames if isinstance(f, AiChunk)]
    assert len(t1_chunks) == 1
    assert t1_chunks[0].text == "Hello"

    # Queue is still alive — feed Turn 2 events (same queue, pump keeps running)
    ctrl.push(_init_evt())
    ctrl.push(_chunk_evt("World"))
    ctrl.push(_result_evt("World"))

    t2_frames = await _collect_until_done(q, timeout=3.0)
    assert any(isinstance(f, AiDone) for f in t2_frames), f"No AiDone in T2: {t2_frames}"
    t2_chunks = [f for f in t2_frames if isinstance(f, AiChunk)]
    assert len(t2_chunks) == 1
    assert t2_chunks[0].text == "World"


# ─────────────────────────────────────────────
# Test 2: Stop recovery — interrupt_session force-emits AiError if process hangs
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_interrupt_force_emits_ai_error_when_process_hangs():
    """If SIGINT doesn't produce a result within grace period, AiError is emitted."""
    proc, ctrl = _make_proc_with_controlled_stdout()

    async def fake_spawn(*args, **kwargs):
        return proc

    with patch("devscope_bridge.session_manager.asyncio.create_subprocess_exec",
               side_effect=fake_spawn):
        q = await mgr.run_prompt("stop-sess", "long running task")

    # Verify session is active
    assert mgr.is_active("stop-sess")

    # Shorten grace period for test speed
    original_grace = mgr._INTERRUPT_GRACE_S
    mgr._INTERRUPT_GRACE_S = 0.1

    try:
        with patch("os.kill") as mock_kill:
            sent = mgr.interrupt_session("stop-sess")
            assert sent is True
            mock_kill.assert_called_once()

        # Wait for the watchdog to fire (grace + small buffer)
        await asyncio.sleep(0.3)

    finally:
        mgr._INTERRUPT_GRACE_S = original_grace

    # AiError must have been emitted to the queue
    error_frames = []
    while not q.empty():
        f = q.get_nowait()
        if isinstance(f, AiError):
            error_frames.append(f)

    assert len(error_frames) >= 1, "Expected AiError after hung interrupt"
    assert "interrupt" in error_frames[0].stderr_tail.lower() or \
           "respawn" in error_frames[0].stderr_tail.lower(), \
           f"Unexpected stderr_tail: {error_frames[0].stderr_tail!r}"


@pytest.mark.asyncio
async def test_interrupt_no_watchdog_if_result_arrives():
    """If a result arrives before the grace period, watchdog does nothing."""
    proc, ctrl = _make_proc_with_controlled_stdout()

    async def fake_spawn(*args, **kwargs):
        return proc

    with patch("devscope_bridge.session_manager.asyncio.create_subprocess_exec",
               side_effect=fake_spawn):
        q = await mgr.run_prompt("intr-ok-sess", "task")

    original_grace = mgr._INTERRUPT_GRACE_S
    mgr._INTERRUPT_GRACE_S = 0.3

    try:
        with patch("os.kill"):
            mgr.interrupt_session("intr-ok-sess")

        # Simulate result arriving before grace expires
        ctrl.push(_init_evt())
        ctrl.push(_result_evt("done"))

        frames = await _collect_until_done(q, timeout=2.0)
        assert any(isinstance(f, AiDone) for f in frames)

        # Wait past grace period — watchdog fires but session was already cleaned
        # by receiving the result normally (turn_count advances, no extra AiError)
        await asyncio.sleep(0.5)

    finally:
        mgr._INTERRUPT_GRACE_S = original_grace

    # No extra AiError should appear after the natural AiDone
    extra_errors = []
    while not q.empty():
        f = q.get_nowait()
        if isinstance(f, AiError):
            extra_errors.append(f)
    # It's acceptable if the watchdog fires and the session was already removed —
    # the _interrupt_watchdog checks and exits early.  At most 0 extra errors.
    assert len(extra_errors) == 0, f"Unexpected extra AiError: {extra_errors}"


# ─────────────────────────────────────────────
# Test 3: Queue reuse across respawns
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_queue_is_reused_across_respawn():
    """out_queue reference is identical before and after a respawn (mode change)."""
    spawned = 0
    proc1, ctrl1 = _make_proc_with_controlled_stdout()
    proc2, ctrl2 = _make_proc_with_controlled_stdout()
    proc2.pid = 22222

    async def fake_spawn(*args, **kwargs):
        nonlocal spawned
        spawned += 1
        return proc1 if spawned == 1 else proc2

    with patch("devscope_bridge.session_manager.asyncio.create_subprocess_exec",
               side_effect=fake_spawn):
        # First prompt — creates queue
        q1 = await mgr.run_prompt("reuse-sess", "msg1", mode="act")

        # Feed turn 1 result so the session is "ready" for a respawn
        ctrl1.push(_init_evt())
        ctrl1.push(_result_evt())
        await _collect_until_done(q1, timeout=2.0)

        # Second prompt with different mode — triggers respawn
        q2 = await mgr.run_prompt("reuse-sess", "msg2", mode="plan")

    assert q1 is q2, "out_queue must be the same object after respawn"
    assert spawned == 2


@pytest.mark.asyncio
async def test_queue_is_reused_on_dead_process_respawn():
    """When the process exits unexpectedly, the next run_prompt reuses the queue."""
    proc1, ctrl1 = _make_proc_with_controlled_stdout()
    proc2, ctrl2 = _make_proc_with_controlled_stdout()
    proc2.pid = 33333

    spawned = 0

    async def fake_spawn(*args, **kwargs):
        nonlocal spawned
        spawned += 1
        return proc1 if spawned == 1 else proc2

    with patch("devscope_bridge.session_manager.asyncio.create_subprocess_exec",
               side_effect=fake_spawn):
        q1 = await mgr.run_prompt("dead-sess", "msg1")

        # Mark process as dead (simulates process exit)
        proc1.returncode = 1

        q2 = await mgr.run_prompt("dead-sess", "msg2")

    assert q1 is q2, "Queue must be reused after dead process respawn"
    assert spawned == 2


# ─────────────────────────────────────────────
# Test 4: Error subtype handling in dispatch_event
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_result_error_subtype_emits_ai_error():
    """result event with is_error=True emits AiError, not AiDone."""
    q: asyncio.Queue = asyncio.Queue()
    event = {
        "type": "result", "subtype": "error",
        "is_error": True, "result": "Something went wrong",
        "session_id": "s1",
    }
    done = await session_reader.dispatch_event("sess", event, q, is_first_message=False)
    assert done is True

    frames = []
    while not q.empty():
        frames.append(q.get_nowait())

    assert any(isinstance(f, AiError) for f in frames), f"Expected AiError: {frames}"
    assert not any(isinstance(f, AiDone) for f in frames), f"Unexpected AiDone: {frames}"


@pytest.mark.asyncio
async def test_result_max_turns_subtype_emits_ai_error():
    """result event with subtype 'error_max_turns' emits AiError."""
    q: asyncio.Queue = asyncio.Queue()
    event = {
        "type": "result", "subtype": "error_max_turns",
        "is_error": True, "result": "Max turns reached",
        "session_id": "s1",
    }
    done = await session_reader.dispatch_event("sess", event, q, is_first_message=False)
    assert done is True

    frames = []
    while not q.empty():
        frames.append(q.get_nowait())

    assert any(isinstance(f, AiError) for f in frames)
    assert not any(isinstance(f, AiDone) for f in frames)


@pytest.mark.asyncio
async def test_result_success_subtype_emits_ai_done():
    """result event with subtype 'success' emits AiDone, not AiError."""
    q: asyncio.Queue = asyncio.Queue()
    event = {
        "type": "result", "subtype": "success",
        "is_error": False, "result": "done",
        "session_id": "s1",
    }
    done = await session_reader.dispatch_event("sess", event, q, is_first_message=False)
    assert done is True

    frames = []
    while not q.empty():
        frames.append(q.get_nowait())

    assert any(isinstance(f, AiDone) for f in frames)
    assert not any(isinstance(f, AiError) for f in frames)


# ─────────────────────────────────────────────
# Test 5: Watchdog emits heartbeat after silence
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_watchdog_emits_heartbeat_after_silence(monkeypatch):
    """If no stdout events for _WATCHDOG_HEARTBEAT_S, AgentActivity is emitted."""
    from devscope_bridge.models import AgentActivity
    import devscope_bridge.session_reader as sr

    # Shorten watchdog interval for test speed
    monkeypatch.setattr(sr, "_WATCHDOG_HEARTBEAT_S", 0.2)
    monkeypatch.setattr(sr, "_WATCHDOG_HARD_CAP_S", 999)

    q: asyncio.Queue = asyncio.Queue()
    activity_event = asyncio.Event()

    # Run the watchdog loop briefly
    watchdog = asyncio.create_task(sr._watchdog_loop("w-sess", q, activity_event))

    # Wait long enough for heartbeat to fire (>0.2s)
    await asyncio.sleep(0.5)
    watchdog.cancel()
    try:
        await watchdog
    except asyncio.CancelledError:
        pass

    frames = []
    while not q.empty():
        frames.append(q.get_nowait())

    activity_frames = [f for f in frames if isinstance(f, AgentActivity)]
    assert len(activity_frames) >= 1, f"Expected heartbeat AgentActivity: {frames}"
    assert "still working" in activity_frames[0].label.lower() or \
           "working" in activity_frames[0].label.lower(), \
           f"Unexpected label: {activity_frames[0].label!r}"


@pytest.mark.asyncio
async def test_watchdog_periodic_heartbeat_survives_activity_resets(monkeypatch):
    """A4/RC-1: the heartbeat is periodic (turn_elapsed-driven), not a one-shot
    latch that activity resets alongside silence.

    The OLD behavior (silence resets BOTH silence_elapsed AND heartbeat_emitted)
    meant a trickling turn — occasional real stdout that keeps resetting
    silence just under the threshold — could go the entire 2400s wall without
    ever pinging the UI. This is the exact regression test for that bug: even
    with activity arriving well before the first threshold, the heartbeat
    still fires once turn_elapsed crosses each _WATCHDOG_HEARTBEAT_S multiple.
    """
    from devscope_bridge.models import AgentActivity
    import devscope_bridge.session_reader as sr

    monkeypatch.setattr(sr, "_WATCHDOG_HEARTBEAT_S", 0.15)
    monkeypatch.setattr(sr, "_WATCHDOG_HARD_CAP_S", 999)

    q: asyncio.Queue = asyncio.Queue()
    activity_event = asyncio.Event()

    watchdog = asyncio.create_task(sr._watchdog_loop("w2-sess", q, activity_event))

    # Simulate activity well before the first heartbeat threshold — under the
    # OLD code this would have reset heartbeat_emitted and suppressed it.
    await asyncio.sleep(0.05)
    activity_event.set()

    # Wait long enough for TWO heartbeat periods of cumulative turn time.
    await asyncio.sleep(0.35)

    watchdog.cancel()
    try:
        await watchdog
    except asyncio.CancelledError:
        pass

    frames = []
    while not q.empty():
        frames.append(q.get_nowait())

    activity_frames = [f for f in frames if isinstance(f, AgentActivity)]
    assert len(activity_frames) >= 2, (
        f"Expected periodic heartbeats despite the activity reset, got: {activity_frames}"
    )
