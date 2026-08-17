"""
test_stuck_turn_handling.py — Perfect stuck-turn handling tests.

Grounded in the official Claude Code docs (code.claude.com/docs/en/headless,
fetched 2026-05-31):

Q1 — CAN HEALTHY TURNS BE SILENT FOR MINUTES?
    YES.  The official SDK streaming-output page documents the message flow:
        AssistantMessage
        ... tool executes ...   ← COMPLETE SILENCE
        ... more streaming events ...
    Between the AssistantMessage and the next streaming event, stdout is
    COMPLETELY SILENT while the tool runs.  For a long `pytest` or `make`
    run this silence can last many minutes.  "No stdout for N seconds" is
    therefore NOT a reliable hang signal on its own — only the hard-cap
    (configured to a value longer than the longest expected tool) should
    trigger a kill.

Q2 — NO OFFICIAL KEEPALIVE/PING IN stream-json.
    There is no keepalive, ping, or periodic heartbeat in the stream-json
    protocol.  The only flags that affect turn length are --max-turns (exit
    with error at N agentic turns) and the ultrareview --timeout flag.
    There is no --idle-timeout or --keepalive flag.

Q3 — STUCK VS WAITING.
    There is no in-protocol way to distinguish "model is computing" from
    "process is dead".  The only reliable signals are:
      - process exit (returncode is set) — certain death
      - stdout silence for > hard-cap — presumed stuck, interrupt + respawn
    A silent stdout during tool execution is NORMAL and expected.

Q4 — BEST PRACTICE FOR HEADLESS ROBUSTNESS.
    Use a hard-cap timeout tuned to the longest expected tool run.  On
    timeout: SIGINT → short grace → SIGKILL → respawn WITHOUT --resume
    (stale session causes the new process to re-process the incomplete turn
    and loop silently).  The session manager already implements this
    three-step sequence.

Tests in this file:

1. WATCHDOG_IDLE_PAUSE: Watchdog does NOT fire while no turn is active
   (session is between turns / freshly spawned).  This is the key fix —
   without it a freshly respawned proc2 gets hard-capped before the next
   user message arrives.

2. WATCHDOG_ACTIVATES_ON_FIRST_STDOUT: Once the first stdout event arrives
   (system/init), the watchdog starts counting and fires the hard-cap.

3. BROWSER_TOOL_TIMEOUT_RETURNS_ERROR_RESULT: When the Chrome extension does
   not respond within its per-action deadline, post_action resolves the
   request itself — HTTP 200 with {ok: False, error: "timeout: ..."} — rather
   than hanging or raising. Claude receives this as a normal tool result and
   continues; the turn does NOT hang forever. (Disconnect mid-action is
   handled the same way, faster: see test_browser_action_deadline.py.)

4. HARD_CAP_ALWAYS_FREES_SESSION: After the hard-cap fires (AiError +
   SIGINT + respawn), the session's turn_done is set so the next run_prompt
   can start a fresh turn.  The session is never left in a permanently-stuck
   state.

5. WATCHDOG_PAUSES_AFTER_TURN_END: After a result event (turn end),
   turn_active_event is cleared so the watchdog pauses and does not count
   inter-turn idle time.
"""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import devscope_bridge.session_reader as sr
import devscope_bridge.session_manager as mgr
import devscope_bridge.session_store as store
import devscope_bridge.browser_relay as relay
from devscope_bridge.models import AiDone, AiError, AgentActivity, SessionReady


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
    """Async iterator fed via an asyncio.Queue; sentinel None closes it."""

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


def _make_proc(pid: int = 9999):
    proc = MagicMock()
    proc.pid = pid
    proc.returncode = None
    ctrl = _ControlledAsyncIterator()
    proc.stdout = ctrl
    proc.stderr = AsyncMock()
    proc.stderr.read = AsyncMock(return_value=b"")
    proc.stdin = MagicMock()
    proc.stdin.write = MagicMock()
    proc.stdin.drain = AsyncMock()

    async def _wait():
        proc.returncode = -2
        return -2
    proc.wait = _wait
    return proc, ctrl


def _result_line(text: str = "ok") -> str:
    return json.dumps({
        "type": "result", "subtype": "success",
        "is_error": False, "result": text,
        "usage": {}, "total_cost_usd": 0, "duration_ms": 0,
    })


def _init_line(sid: str = "sess-001") -> str:
    return json.dumps({"type": "system", "subtype": "init", "session_id": sid})


def _chunk_line(text: str) -> str:
    return json.dumps({
        "type": "stream_event",
        "event": {"type": "content_block_delta", "index": 0,
                  "delta": {"type": "text_delta", "text": text}},
    })


# ─────────────────────────────────────────────
# Test 1: Watchdog does NOT fire between turns (idle state)
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_watchdog_does_not_fire_when_session_is_idle(monkeypatch):
    """Grounded finding: between turns, the watchdog must NOT count silence.

    When turn_done is SET (idle), the watchdog freezes its timer.
    This prevents a freshly-respawned proc from being hard-capped before the
    next user message arrives — the most common false-positive hang kill.
    """
    monkeypatch.setattr(sr, "_WATCHDOG_HEARTBEAT_S", 0.05)
    monkeypatch.setattr(sr, "_WATCHDOG_HARD_CAP_S", 0.1)

    proc, ctrl = _make_proc(pid=7001)
    q: asyncio.Queue = asyncio.Queue()
    turn_done = asyncio.Event()
    turn_done.set()  # Session is IDLE — no turn in progress

    interrupt_called = []

    def fake_interrupt():
        interrupt_called.append(True)

    reader_task = asyncio.create_task(
        sr.continuous_reader("idle-sess", proc, q, turn_done,
                             hard_interrupt_fn=fake_interrupt)
    )

    # Wait well past both thresholds
    await asyncio.sleep(0.5)

    ctrl.close()
    reader_task.cancel()
    try:
        await asyncio.wait_for(reader_task, timeout=1.0)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass

    # Must NOT have fired: session was idle, no turn was running
    assert len(interrupt_called) == 0, (
        "Watchdog must NOT fire when session is between turns (idle). "
        "A healthy persistent process sitting idle is not stuck."
    )
    frames = [q.get_nowait() for _ in range(q.qsize())]
    error_frames = [f for f in frames if isinstance(f, AiError)]
    heartbeat_frames = [f for f in frames if isinstance(f, AgentActivity)]
    assert len(error_frames) == 0, (
        f"No AiError during idle: {[f.stderr_tail for f in error_frames]}"
    )
    assert len(heartbeat_frames) == 0, (
        "No heartbeat AgentActivity during idle"
    )


# ─────────────────────────────────────────────
# Test 2: Watchdog activates on first stdout event then fires hard-cap
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_watchdog_activates_after_first_stdout_then_fires(monkeypatch):
    """Once stdout arrives (init), watchdog starts counting and fires the hard-cap.

    Rationale: the session was idle at spawn time (turn_done set), then
    run_prompt clears turn_done and writes to stdin.  The first stdout event
    (system/init) signals the turn is live; the watchdog starts from that point.
    """
    monkeypatch.setattr(sr, "_WATCHDOG_HEARTBEAT_S", 0.05)
    monkeypatch.setattr(sr, "_WATCHDOG_HARD_CAP_S", 0.15)

    proc, ctrl = _make_proc(pid=7002)
    q: asyncio.Queue = asyncio.Queue()
    turn_done = asyncio.Event()
    # Start as active turn (simulating run_prompt clearing turn_done)

    interrupt_called = []

    def fake_interrupt():
        interrupt_called.append(True)
        ctrl.close()

    reader_task = asyncio.create_task(
        sr.continuous_reader("active-sess", proc, q, turn_done,
                             hard_interrupt_fn=fake_interrupt)
    )

    # Push an init event — this activates the watchdog timer
    ctrl.push(_init_line("sid-active"))
    # Now go silent (simulate tool execution) — watchdog should fire after 0.15s
    await asyncio.sleep(0.5)

    try:
        await asyncio.wait_for(reader_task, timeout=1.0)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        reader_task.cancel()
        try:
            await reader_task
        except asyncio.CancelledError:
            pass

    assert len(interrupt_called) >= 1, (
        "Hard-cap must fire after init + silence exceeds _WATCHDOG_HARD_CAP_S"
    )
    frames = [q.get_nowait() for _ in range(q.qsize())]
    error_frames = [f for f in frames if isinstance(f, AiError)]
    assert len(error_frames) >= 1, "AiError must arrive from hard-cap"


# ─────────────────────────────────────────────
# Test 3: Browser tool timeout returns error result, not hang
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_browser_tool_timeout_returns_error_dict_not_hang():
    """When the extension never replies, post_action resolves ok=False — it
    does not hang and does not raise.

    Official docs confirm: no keepalive in stream-json; the only protection
    against a browser tool that never returns is a per-tool deadline at the
    relay layer (see browser_relay._action_timeout_s / _DEFAULT_ACTION_TIMEOUT_S).
    """
    from devscope_bridge.browser_relay import post_action, ActionRequest
    from devscope_bridge import browser_relay

    # Register a WS that accepts send_text but never resolves the future
    class _SilentWebSocket:
        async def send_text(self, _text: str) -> None:
            pass  # Never resolves the action

    browser_relay._active_ws["timeout-sess"] = _SilentWebSocket()

    # Shorten the timeout so the test runs fast
    original = browser_relay._DEFAULT_ACTION_TIMEOUT_S
    browser_relay._DEFAULT_ACTION_TIMEOUT_S = 0.05

    body = ActionRequest(tool="browser_get_page_info", args={}, session="timeout-sess")
    try:
        result = await post_action(body, auth=None)
        assert result["ok"] is False, f"Expected ok=False on timeout, got {result}"
        assert "timeout" in (result["error"] or "").lower(), (
            f"Expected 'timeout' in error: {result['error']!r}"
        )
    finally:
        browser_relay._DEFAULT_ACTION_TIMEOUT_S = original
        browser_relay._active_ws.pop("timeout-sess", None)
        # Clean up any pending futures
        for fid in list(browser_relay._pending_actions.keys()):
            fut = browser_relay._pending_actions.pop(fid, None)
            if fut and not fut.done():
                fut.cancel()
        browser_relay._action_session.clear()


@pytest.mark.asyncio
async def test_browser_tool_timeout_cleans_up_pending_action():
    """After a timeout, the pending action is removed from _pending_actions.

    A leaked future would cause resolve_browser_result to silently drop a
    late-arriving browser_result (correct), but it would also prevent the
    action_id slot from being reused (no practical problem since UUIDs are
    unique, but the dict should not grow without bound).
    """
    from devscope_bridge.browser_relay import post_action, ActionRequest
    from devscope_bridge import browser_relay

    class _SilentWebSocket:
        async def send_text(self, _text: str) -> None:
            pass

    browser_relay._active_ws["cleanup-sess"] = _SilentWebSocket()
    original = browser_relay._DEFAULT_ACTION_TIMEOUT_S
    browser_relay._DEFAULT_ACTION_TIMEOUT_S = 0.05

    body = ActionRequest(tool="browser_click", args={"selector": "#btn"},
                         session="cleanup-sess")
    try:
        result = await post_action(body, auth=None)
        assert result["ok"] is False
    finally:
        browser_relay._DEFAULT_ACTION_TIMEOUT_S = original
        browser_relay._active_ws.pop("cleanup-sess", None)

    # All pending actions must be cleaned up by the finally block in _send_action
    assert len(browser_relay._pending_actions) == 0, (
        "Timed-out pending actions must be removed from _pending_actions "
        "so the dict does not grow without bound"
    )
    assert len(browser_relay._action_session) == 0, (
        "Timed-out pending actions must be removed from _action_session too"
    )


# ─────────────────────────────────────────────
# Test 4: Hard-cap always frees the session (turn_done set after respawn)
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_hard_cap_always_frees_session_turn_done(monkeypatch):
    """After hard-cap fires and respawn completes, turn_done is SET.

    This guarantees that:
    1. The next run_prompt can start a fresh turn (turn_done.clear() works).
    2. The idle-eviction task sees the session as idle (not stuck mid-turn).
    3. The watchdog on the new proc starts in paused state (no false-positive).
    """
    monkeypatch.setattr(mgr, "_INTERRUPT_GRACE_S", 0.05)
    monkeypatch.setattr(sr, "_WATCHDOG_HEARTBEAT_S", 0.05)
    monkeypatch.setattr(sr, "_WATCHDOG_HARD_CAP_S", 0.1)

    proc1, ctrl1 = _make_proc(pid=8001)
    proc2, ctrl2 = _make_proc(pid=8002)
    spawn_count = 0

    async def fake_spawn(*args, **kwargs):
        nonlocal spawn_count
        spawn_count += 1
        return proc1 if spawn_count == 1 else proc2

    with patch("devscope_bridge.session_manager.asyncio.create_subprocess_exec",
               side_effect=fake_spawn), \
         patch("os.kill"):
        q = await mgr.run_prompt("free-sess", "first message")
        ctrl1.push(json.dumps({"type": "system", "subtype": "init",
                               "session_id": "sid-free"}))
        # Let the hard-cap fire and respawn complete
        await asyncio.sleep(0.5)

        active = mgr._sessions.get("free-sess")
        assert active is not None, "Session must survive hard-cap respawn"
        assert active.turn_done.is_set(), (
            "turn_done must be SET after hard-cap forced respawn. "
            "If not set, the next run_prompt cannot clear it to start a new turn, "
            "and idle-eviction will never fire."
        )
        assert spawn_count == 2, f"Expected 2 spawns (original + respawn), got {spawn_count}"


# ─────────────────────────────────────────────
# Test 5: Watchdog pauses after result event (turn end)
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_watchdog_pauses_after_result_event(monkeypatch):
    """After a result event (turn end), the watchdog must pause.

    Official docs: after the final result message, the persistent process sits
    idle waiting for the next stdin message.  The watchdog must not count this
    idle time as a stuck turn — otherwise every long-running session would be
    killed after _WATCHDOG_HARD_CAP_S of inter-message silence.
    """
    monkeypatch.setattr(sr, "_WATCHDOG_HEARTBEAT_S", 0.05)
    monkeypatch.setattr(sr, "_WATCHDOG_HARD_CAP_S", 0.1)

    proc, ctrl = _make_proc(pid=9001)
    q: asyncio.Queue = asyncio.Queue()
    turn_done = asyncio.Event()
    # Start as active (turn in progress)

    interrupt_called = []

    def fake_interrupt():
        interrupt_called.append(True)

    reader_task = asyncio.create_task(
        sr.continuous_reader("pause-sess", proc, q, turn_done,
                             hard_interrupt_fn=fake_interrupt)
    )

    # Push init + chunk + result — this completes the turn
    ctrl.push(_init_line("sid-pause"))
    ctrl.push(_chunk_line("turn done"))
    ctrl.push(_result_line("turn done"))
    # Wait for result to be processed
    await asyncio.sleep(0.05)

    # Now go silent (between turns) — well past the hard-cap threshold
    await asyncio.sleep(0.4)

    ctrl.close()
    reader_task.cancel()
    try:
        await asyncio.wait_for(reader_task, timeout=1.0)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass

    # Hard-cap must NOT have fired: we're between turns (watchdog paused)
    assert len(interrupt_called) == 0, (
        "Watchdog must NOT fire between turns after result event. "
        "Inter-turn silence is normal for a healthy persistent process."
    )
    frames = [q.get_nowait() for _ in range(q.qsize())]
    error_frames = [f for f in frames if isinstance(f, AiError)]
    # Only non-watchdog AiError (from proc exit due to ctrl.close()) is expected;
    # the watchdog itself must not have fired.
    watchdog_errors = [
        f for f in error_frames
        if "stuck" in (f.stderr_tail or "").lower()
        or "interrupt" in (f.stderr_tail or "").lower()
    ]
    assert len(watchdog_errors) == 0, (
        f"Watchdog AiError must not appear between turns: "
        f"{[f.stderr_tail for f in watchdog_errors]}"
    )
    done_frames = [f for f in frames if isinstance(f, AiDone)]
    assert len(done_frames) == 1, f"Expected AiDone from the completed turn: {frames}"
