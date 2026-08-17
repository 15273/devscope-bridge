"""
test_watchdog_hard_timeout.py

Tests for the two-tier watchdog and the control-protocol non-existence finding.

1. HARD TIMEOUT: After _WATCHDOG_HARD_CAP_S of silence, the watchdog emits
   AiError and calls the hard_interrupt_fn — guaranteeing the UI unblocks.

2. HARD CAP FIRES AFTER HEARTBEAT: The hard-cap uses a separate flag from the
   heartbeat, so it fires even if the heartbeat already fired (bug fix: the
   old code shared heartbeat_emitted, meaning hard cap never fired after
   the heartbeat had already triggered).

3. HEARTBEAT STILL FIRES: The heartbeat tier (_WATCHDOG_HEARTBEAT_S) still
   emits AgentActivity("still working…") before the hard cap.

4. WATCHDOG RESETS ON ACTIVITY BETWEEN TIERS: If activity arrives after
   the heartbeat but before the hard cap, both flags reset and the sequence
   starts over.

5. CONTROL_REQUEST NON-EXISTENCE: Empirically confirmed (2026-05-30) that
   claude --print --input-format stream-json does NOT emit control_request
   events in any permission mode.  dispatch_event handles unknown event types
   by logging at DEBUG and returning False (turn not done) — it never hangs.
   This test confirms that a synthetic control_request-style event is handled
   gracefully (not treated as turn-end, no crash).

6. HARD_INTERRUPT_FN IN CONTINUOUS_READER: continuous_reader correctly passes
   the supplied hard_interrupt_fn to the watchdog.

7. NO DOUBLE AIDONE AFTER HARD CAP: After the watchdog emits AiError, a
   subsequent result event (if the process somehow recovers) still emits AiDone
   normally — the hard cap does not permanently break the reader.
"""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import devscope_bridge.session_reader as sr
import devscope_bridge.session_manager as mgr
import devscope_bridge.session_store as store
from devscope_bridge.models import AgentActivity, AiDone, AiError, SessionReady


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


# ─────────────────────────────────────────────
# Test 1: Hard cap emits AiError and calls interrupt fn
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_watchdog_hard_cap_emits_ai_error_and_calls_interrupt(monkeypatch):
    """After _WATCHDOG_HARD_CAP_S, watchdog emits AiError and calls hard_interrupt_fn."""
    monkeypatch.setattr(sr, "_WATCHDOG_HEARTBEAT_S", 0.1)
    monkeypatch.setattr(sr, "_WATCHDOG_HARD_CAP_S", 0.2)

    q: asyncio.Queue = asyncio.Queue()
    activity_event = asyncio.Event()
    interrupt_called = []

    def fake_interrupt():
        interrupt_called.append(True)

    watchdog = asyncio.create_task(
        sr._watchdog_loop("sess", q, activity_event, hard_interrupt_fn=fake_interrupt)
    )

    # Wait past hard cap (0.2s + buffer)
    await asyncio.sleep(0.5)
    watchdog.cancel()
    try:
        await watchdog
    except asyncio.CancelledError:
        pass

    frames = []
    while not q.empty():
        frames.append(q.get_nowait())

    error_frames = [f for f in frames if isinstance(f, AiError)]
    assert len(error_frames) >= 1, f"Expected AiError from hard cap, got: {frames}"
    assert "stuck" in error_frames[0].stderr_tail.lower() or \
           "interrupt" in error_frames[0].stderr_tail.lower(), \
           f"Unexpected AiError message: {error_frames[0].stderr_tail!r}"
    assert error_frames[0].exit_code == -1

    assert len(interrupt_called) >= 1, "hard_interrupt_fn must be called when hard cap fires"


# ─────────────────────────────────────────────
# Test 2: Hard cap fires even after heartbeat already emitted
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_watchdog_hard_cap_fires_after_heartbeat(monkeypatch):
    """Hard cap must fire even if the heartbeat has already emitted (separate flags)."""
    monkeypatch.setattr(sr, "_WATCHDOG_HEARTBEAT_S", 0.1)
    monkeypatch.setattr(sr, "_WATCHDOG_HARD_CAP_S", 0.3)

    q: asyncio.Queue = asyncio.Queue()
    activity_event = asyncio.Event()
    interrupt_called = []

    def fake_interrupt():
        interrupt_called.append(True)

    watchdog = asyncio.create_task(
        sr._watchdog_loop("sess2", q, activity_event, hard_interrupt_fn=fake_interrupt)
    )

    # Wait past both heartbeat AND hard cap
    await asyncio.sleep(0.6)
    watchdog.cancel()
    try:
        await watchdog
    except asyncio.CancelledError:
        pass

    frames = []
    while not q.empty():
        frames.append(q.get_nowait())

    activity_frames = [f for f in frames if isinstance(f, AgentActivity)]
    error_frames = [f for f in frames if isinstance(f, AiError)]

    assert len(activity_frames) >= 1, f"Heartbeat AgentActivity missing: {frames}"
    assert len(error_frames) >= 1, f"Hard-cap AiError missing: {frames}"
    # Heartbeat must come before AiError
    first_activity_idx = next(i for i, f in enumerate(frames) if isinstance(f, AgentActivity))
    first_error_idx = next(i for i, f in enumerate(frames) if isinstance(f, AiError))
    assert first_activity_idx < first_error_idx, \
        "Heartbeat AgentActivity must appear before hard-cap AiError"
    assert len(interrupt_called) >= 1


# ─────────────────────────────────────────────
# Test 3: Activity between tiers resets both flags
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_watchdog_activity_between_tiers_resets_hard_cap(monkeypatch):
    """Activity arriving after heartbeat but before hard cap resets both timers."""
    monkeypatch.setattr(sr, "_WATCHDOG_HEARTBEAT_S", 0.1)
    monkeypatch.setattr(sr, "_WATCHDOG_HARD_CAP_S", 0.4)

    q: asyncio.Queue = asyncio.Queue()
    activity_event = asyncio.Event()
    interrupt_called = []

    def fake_interrupt():
        interrupt_called.append(True)

    watchdog = asyncio.create_task(
        sr._watchdog_loop("sess3", q, activity_event, hard_interrupt_fn=fake_interrupt)
    )

    # Let heartbeat fire (0.1s)
    await asyncio.sleep(0.2)
    # Simulate activity — resets elapsed and both flags
    activity_event.set()
    # Now wait past the original hard cap threshold from t=0, but NOT from the reset
    await asyncio.sleep(0.25)

    watchdog.cancel()
    try:
        await watchdog
    except asyncio.CancelledError:
        pass

    frames = []
    while not q.empty():
        frames.append(q.get_nowait())

    error_frames = [f for f in frames if isinstance(f, AiError)]
    # Hard cap should NOT have fired: total elapsed since reset is only ~0.25s < 0.4s
    assert len(interrupt_called) == 0, \
        f"Hard interrupt must not fire within hard-cap window after reset: {frames}"
    assert len(error_frames) == 0, \
        f"AiError must not appear within hard-cap window after reset: {frames}"


# ─────────────────────────────────────────────
# Test 4: No hard_interrupt_fn → still emits AiError, no crash
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_watchdog_hard_cap_without_interrupt_fn(monkeypatch):
    """Hard cap works (emits AiError) even when hard_interrupt_fn is None."""
    monkeypatch.setattr(sr, "_WATCHDOG_HEARTBEAT_S", 0.1)
    monkeypatch.setattr(sr, "_WATCHDOG_HARD_CAP_S", 0.2)

    q: asyncio.Queue = asyncio.Queue()
    activity_event = asyncio.Event()

    watchdog = asyncio.create_task(
        sr._watchdog_loop("sess4", q, activity_event, hard_interrupt_fn=None)
    )

    await asyncio.sleep(0.5)
    watchdog.cancel()
    try:
        await watchdog
    except asyncio.CancelledError:
        pass

    frames = []
    while not q.empty():
        frames.append(q.get_nowait())

    error_frames = [f for f in frames if isinstance(f, AiError)]
    assert len(error_frames) >= 1, f"AiError must be emitted even without interrupt fn: {frames}"


# ─────────────────────────────────────────────
# Test 5: control_request handled as unknown (no hang, no crash)
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_control_request_event_is_handled_gracefully():
    """A synthetic control_request event is treated as unknown — no crash, turn not ended.

    Empirical finding (2026-05-30): claude --print --input-format stream-json does NOT
    emit control_request events in any permission mode (bypassPermissions or default).
    The original freeze hypothesis was wrong.  The real fix is the hard-cap watchdog.

    This test confirms that if such an event ever appeared (e.g. in a future claude
    version), dispatch_event would handle it gracefully via the else/DEBUG path —
    not as a turn-end and not causing a crash.
    """
    q: asyncio.Queue = asyncio.Queue()

    synthetic_control_request = {
        "type": "control_request",
        "subtype": "can_use_tool",
        "request_id": "ctrl-001",
        "tool_name": "Bash",
        "tool_input": {"command": "ls /tmp"},
    }

    done = await sr.dispatch_event("sess", synthetic_control_request, q, is_first_message=False)

    # Must NOT end the turn
    assert done is False, "control_request must not signal end-of-turn"

    # Must NOT have put any frames on the queue (falls through to DEBUG log)
    assert q.empty(), "control_request must not put frames on the queue"


# ─────────────────────────────────────────────
# Test 6: continuous_reader passes hard_interrupt_fn to the watchdog
# ─────────────────────────────────────────────

class _ControlledAsyncIterator:
    """Async iterator whose items are fed via an asyncio.Queue."""

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


def _make_proc_ctrl():
    proc = MagicMock()
    proc.pid = 55555
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


@pytest.mark.asyncio
async def test_continuous_reader_passes_hard_interrupt_fn(monkeypatch):
    """continuous_reader wires hard_interrupt_fn into the watchdog (hard cap fires)."""
    monkeypatch.setattr(sr, "_WATCHDOG_HEARTBEAT_S", 0.1)
    monkeypatch.setattr(sr, "_WATCHDOG_HARD_CAP_S", 0.2)

    proc, ctrl = _make_proc_ctrl()
    q: asyncio.Queue = asyncio.Queue()
    turn_done = asyncio.Event()
    interrupt_called = []

    def fake_interrupt():
        interrupt_called.append(True)

    # Start the reader — no events pushed, so it will just wait (silent → watchdog fires)
    reader_task = asyncio.create_task(
        sr.continuous_reader(
            "rd-sess", proc, q, turn_done, hard_interrupt_fn=fake_interrupt,
        )
    )

    # Wait past hard cap
    await asyncio.sleep(0.5)

    # Close the iterator so the reader task can exit cleanly
    ctrl.close()
    reader_task.cancel()
    try:
        await asyncio.wait_for(reader_task, timeout=1.0)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass

    assert len(interrupt_called) >= 1, "hard_interrupt_fn must be called via continuous_reader"

    frames = []
    while not q.empty():
        frames.append(q.get_nowait())
    error_frames = [f for f in frames if isinstance(f, AiError)]
    assert len(error_frames) >= 1, f"AiError must appear on queue: {frames}"


# ─────────────────────────────────────────────
# Test 7: After hard-cap AiError, a recovered result still emits AiDone
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_result_event_after_hard_cap_still_emits_ai_done():
    """dispatch_event still emits AiDone for result/success even after a hard-cap freeze.

    Hard cap and AiError come from the watchdog (external).  dispatch_event
    is stateless — it emits AiDone for every success result regardless of prior
    watchdog events.  This confirms the reader does not permanently break.
    """
    q: asyncio.Queue = asyncio.Queue()

    result_event = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": "recovered ok",
        "session_id": "s1",
        "usage": {},
        "total_cost_usd": 0,
        "duration_ms": 0,
    }

    done = await sr.dispatch_event("sess", result_event, q, is_first_message=False)
    assert done is True

    frames = []
    while not q.empty():
        frames.append(q.get_nowait())

    assert any(isinstance(f, AiDone) for f in frames), f"Expected AiDone: {frames}"
    assert not any(isinstance(f, AiError) for f in frames), f"Unexpected AiError: {frames}"


# ─────────────────────────────────────────────
# Trickle stream_event must not skip wall-cap
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_watchdog_wall_cap_fires_despite_trickle_activity(monkeypatch):
    """Periodic activity resets silence but wall-clock turn cap still interrupts."""
    monkeypatch.setattr(sr, "_WATCHDOG_HEARTBEAT_S", 0.05)
    monkeypatch.setattr(sr, "_WATCHDOG_MEDIC_S", 99.0)
    monkeypatch.setattr(sr, "_WATCHDOG_HARD_CAP_S", 99.0)
    monkeypatch.setattr(sr, "_WATCHDOG_TURN_WALL_MEDIC_S", 99.0)
    monkeypatch.setattr(sr, "_WATCHDOG_TURN_WALL_CAP_S", 0.25)
    monkeypatch.setattr(sr, "_WATCHDOG_TURN_ABSOLUTE_CAP_S", 99.0)

    q: asyncio.Queue = asyncio.Queue()
    activity_event = asyncio.Event()
    turn_active = asyncio.Event()
    turn_active.set()
    interrupt_called: list[bool] = []

    async def trickle():
        while True:
            activity_event.set()
            await asyncio.sleep(0.02)

    trickle_task = asyncio.create_task(trickle())
    watchdog = asyncio.create_task(sr._watchdog_loop(
        "trickle", q, activity_event,
        hard_interrupt_fn=lambda: interrupt_called.append(True),
        turn_active_event=turn_active,
    ))

    await asyncio.sleep(0.55)
    trickle_task.cancel()
    watchdog.cancel()
    try:
        await trickle_task
    except asyncio.CancelledError:
        pass
    try:
        await watchdog
    except asyncio.CancelledError:
        pass

    assert interrupt_called, "wall-cap must fire even when stdout trickles every tick"
    assert any(isinstance(f, AiError) for f in _drain_q(q))


def _drain_q(q: asyncio.Queue) -> list:
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


@pytest.mark.asyncio
async def test_watchdog_long_running_still_hits_absolute_cap(monkeypatch):
    """long_running skips silence kill but absolute turn ceiling still frees UI."""
    monkeypatch.setattr(sr, "_WATCHDOG_HEARTBEAT_S", 0.05)
    monkeypatch.setattr(sr, "_WATCHDOG_MEDIC_S", 99.0)
    monkeypatch.setattr(sr, "_WATCHDOG_HARD_CAP_S", 0.05)  # would fire immediately if not exempt
    monkeypatch.setattr(sr, "_WATCHDOG_TURN_WALL_MEDIC_S", 99.0)
    monkeypatch.setattr(sr, "_WATCHDOG_TURN_WALL_CAP_S", 99.0)
    monkeypatch.setattr(sr, "_WATCHDOG_TURN_ABSOLUTE_CAP_S", 0.3)

    sr.mark_long_running("orch-worker")
    try:
        q: asyncio.Queue = asyncio.Queue()
        activity_event = asyncio.Event()
        turn_active = asyncio.Event()
        turn_active.set()
        interrupt_called: list[bool] = []

        watchdog = asyncio.create_task(sr._watchdog_loop(
            "orch-worker", q, activity_event,
            hard_interrupt_fn=lambda: interrupt_called.append(True),
            turn_active_event=turn_active,
        ))
        await asyncio.sleep(0.15)
        assert not interrupt_called, "silence hard-cap must be skipped for long_running"
        await asyncio.sleep(0.35)
        watchdog.cancel()
        try:
            await watchdog
        except asyncio.CancelledError:
            pass
        assert interrupt_called, "absolute cap must still interrupt long_running"
    finally:
        sr.clear_long_running("orch-worker")


@pytest.mark.asyncio
async def test_watchdog_medic_defer_has_max(monkeypatch):
    """Wedged medic_active cannot defer hard-cap forever."""
    monkeypatch.setattr(sr, "_WATCHDOG_HEARTBEAT_S", 0.05)
    monkeypatch.setattr(sr, "_WATCHDOG_MEDIC_S", 99.0)
    monkeypatch.setattr(sr, "_WATCHDOG_HARD_CAP_S", 0.1)
    monkeypatch.setattr(sr, "_WATCHDOG_TURN_WALL_MEDIC_S", 99.0)
    monkeypatch.setattr(sr, "_WATCHDOG_TURN_WALL_CAP_S", 99.0)
    monkeypatch.setattr(sr, "_WATCHDOG_TURN_ABSOLUTE_CAP_S", 99.0)
    monkeypatch.setattr(sr, "_WATCHDOG_MEDIC_DEFER_MAX_S", 0.2)

    q: asyncio.Queue = asyncio.Queue()
    activity_event = asyncio.Event()
    medic_active = asyncio.Event()
    medic_active.set()
    interrupt_called: list[bool] = []

    watchdog = asyncio.create_task(sr._watchdog_loop(
        "wedged-medic", q, activity_event,
        hard_interrupt_fn=lambda: interrupt_called.append(True),
        medic_active=medic_active,
    ))
    await asyncio.sleep(0.2)
    assert not interrupt_called, "should still defer within medic defer window"
    await asyncio.sleep(0.35)
    watchdog.cancel()
    try:
        await watchdog
    except asyncio.CancelledError:
        pass
    assert interrupt_called, "hard-cap must fire after medic defer max"
