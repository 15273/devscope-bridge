"""
test_respawn_then_answer.py — Regression test for the "stuck after respawn" bug.

REPRO: After the watchdog hard-cap fires (emits AiError + SIGINTs + respawns),
the NEXT user message gets NO reply.  The session appears to be alive (pid
changes, stdin write succeeds) but no AiChunk/AiDone ever arrives on the queue.

ROOT CAUSE: _watchdog_respawn and _interrupt_watchdog were respawning the new
process with --resume <session_id>, where <session_id> belonged to the
interrupted (SIGINT-killed) conversation.  Claude tries to complete the
interrupted turn first, ignoring the new stdin message.  The session loops
between hard-cap → AiError → respawn-with-broken-resume → hard-cap.

FIX (three parts):
  1. _watchdog_respawn / _interrupt_watchdog clear the stored session_id via
     session_store.clear_session_id() BEFORE respawning.  The new process
     therefore starts without --resume (fresh conversation).
  2. turn_done is set() after forced respawn so idle-eviction bookkeeping is
     consistent (the interrupted turn IS over from the bridge's perspective).
  3. continuous_reader suppresses the redundant post-exit AiError when the
     process exit was caused by the hard-cap (which already emitted one).

Tests:
  1. After watchdog hard-cap + respawn, the next user message gets an AiDone.
  2. The respawned proc is NOT spawned with --resume (session_id was cleared).
  3. turn_done is SET after forced hard-cap respawn.
  4. After user-triggered interrupt + forced respawn, next message is answered.
  5. No duplicate AiError when hard-cap fires (suppress post-exit AiError).
  6. session_store.clear_session_id leaves all other metadata intact.
"""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import devscope_bridge.session_manager as mgr
import devscope_bridge.session_reader as sr
import devscope_bridge.session_store as store
from devscope_bridge.models import AiChunk, AiDone, AiError, SessionReady


# ─────────────────────────────────────────────
# Fixtures
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


def _make_proc(pid: int = 11111):
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


def _init_line(sid: str = "sess-001") -> str:
    return json.dumps({"type": "system", "subtype": "init", "session_id": sid})


def _chunk_line(text: str) -> str:
    return json.dumps({
        "type": "stream_event",
        "event": {"type": "content_block_delta", "index": 0,
                  "delta": {"type": "text_delta", "text": text}},
    })


def _result_line(text: str = "ok") -> str:
    return json.dumps({
        "type": "result", "subtype": "success",
        "is_error": False, "result": text,
    })


async def _collect_until_done(q: asyncio.Queue, timeout: float = 3.0) -> list:
    """Collect frames until AiDone or AiError (inclusive), with timeout."""
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


async def _collect_until_ai_done(q: asyncio.Queue, timeout: float = 3.0) -> list:
    """Collect frames until AiDone specifically (skipping AiError), with timeout.

    Used when prior-turn AiErrors are already buffered on the queue and the
    caller only cares about the new turn's AiDone.
    """
    frames = []
    try:
        async with asyncio.timeout(timeout):
            while True:
                f = await q.get()
                frames.append(f)
                if isinstance(f, AiDone):
                    break
    except TimeoutError:
        pass
    return frames


# ─────────────────────────────────────────────
# Test 1: After hard-cap respawn the NEXT message is answered
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_next_message_answered_after_hard_cap_respawn(monkeypatch):
    """Regression: after _watchdog_respawn fires, the next user message gets AiDone."""
    # Shorten timers so the test runs fast
    monkeypatch.setattr(mgr, "_INTERRUPT_GRACE_S", 0.05)
    monkeypatch.setattr(sr, "_WATCHDOG_HEARTBEAT_S", 0.05)
    monkeypatch.setattr(sr, "_WATCHDOG_HARD_CAP_S", 0.1)

    proc1, ctrl1 = _make_proc(pid=1000)
    proc2, ctrl2 = _make_proc(pid=2000)

    spawn_count = 0
    spawn_args: list[list] = []

    async def fake_spawn(*args, **kwargs):
        nonlocal spawn_count
        spawn_count += 1
        spawn_args.append(list(args))
        return proc1 if spawn_count == 1 else proc2

    # Keep both patches (spawn + os.kill) active for the whole test including
    # the background _watchdog_respawn task that fires after the hard-cap.
    with patch("devscope_bridge.session_manager.asyncio.create_subprocess_exec",
               side_effect=fake_spawn), \
         patch("os.kill"):
        # Turn 1 — push init + hang (simulate a stuck turn, no result)
        q = await mgr.run_prompt("hc-sess", "first message")
        ctrl1.push(_init_line("sid-abc"))
        # Let the session_id get stored
        await asyncio.sleep(0.05)

        # Let hard-cap fire (0.1s) + grace period (0.05s) + buffer
        await asyncio.sleep(0.3)

        # Hard-cap AiError must have arrived
        hc_errors = []
        while not q.empty():
            f = q.get_nowait()
            if isinstance(f, AiError):
                hc_errors.append(f)
        assert len(hc_errors) >= 1, (
            f"Expected hard-cap AiError, got nothing — queue was empty"
        )

        # Proc2 should have been spawned by the watchdog respawn
        assert spawn_count == 2, f"Expected 2 spawns (original + respawn), got {spawn_count}"

        # Verify proc2 was NOT spawned with --resume (session_id was cleared)
        second_args = spawn_args[1]
        assert "--resume" not in second_args, (
            f"Respawned proc must NOT use --resume after hard-cap kill, "
            f"but got args: {second_args}"
        )

        # turn_done must be SET after the hard-cap respawn
        active = mgr._sessions.get("hc-sess")
        assert active is not None, "Session must still be in _sessions after respawn"
        assert active.turn_done.is_set(), (
            "turn_done must be set() after hard-cap forced respawn so idle-eviction "
            "works correctly and the next run_prompt clears it cleanly"
        )

        # Now send a NEW message — it must be answered
        q2 = await mgr.run_prompt("hc-sess", "second message after respawn")
        assert q2 is q, "Queue must be the same stable object after respawn"

        # Feed proc2's reply
        ctrl2.push(_init_line("sid-new"))
        ctrl2.push(_chunk_line("hello after respawn"))
        ctrl2.push(_result_line("hello after respawn"))

        frames = await _collect_until_done(q2, timeout=3.0)
        done_frames = [f for f in frames if isinstance(f, AiDone)]
        assert len(done_frames) == 1, (
            f"Expected AiDone after respawn+second message, got: "
            f"{[type(f).__name__ for f in frames]}"
        )
        chunks = [f for f in frames if isinstance(f, AiChunk)]
        assert any(c.text == "hello after respawn" for c in chunks), (
            f"Expected chunk 'hello after respawn', got: {[c.text for c in chunks]}"
        )


# ─────────────────────────────────────────────
# Test 2: After user-interrupt forced respawn the next message is answered
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_next_message_answered_after_user_interrupt_forced_respawn(monkeypatch):
    """Regression: after _interrupt_watchdog forces a respawn, next message gets AiDone."""
    monkeypatch.setattr(mgr, "_INTERRUPT_GRACE_S", 0.05)

    proc1, ctrl1 = _make_proc(pid=3000)
    proc2, ctrl2 = _make_proc(pid=4000)

    spawn_count = 0
    spawn_args: list[list] = []

    async def fake_spawn(*args, **kwargs):
        nonlocal spawn_count
        spawn_count += 1
        spawn_args.append(list(args))
        return proc1 if spawn_count == 1 else proc2

    # Keep spawn patch + os.kill patch active for background _interrupt_watchdog task
    with patch("devscope_bridge.session_manager.asyncio.create_subprocess_exec",
               side_effect=fake_spawn), \
         patch("os.kill"):
        q = await mgr.run_prompt("ui-sess", "long task")
        ctrl1.push(_init_line("sid-ui"))
        await asyncio.sleep(0.02)

        # Trigger user interrupt — process won't produce a result
        mgr.interrupt_session("ui-sess")
        # Wait past grace period — _interrupt_watchdog fires and respawns
        await asyncio.sleep(0.2)

        assert spawn_count == 2, f"Expected 2 spawns, got {spawn_count}"

        # Respawn must NOT use --resume
        second_args = spawn_args[1]
        assert "--resume" not in second_args, (
            f"Forced respawn after user interrupt must not --resume a killed session: {second_args}"
        )

        # turn_done must be set after forced respawn
        active = mgr._sessions.get("ui-sess")
        assert active is not None
        assert active.turn_done.is_set(), "turn_done must be set after _interrupt_watchdog respawn"

        # Next message must reach the new proc and be answered
        q2 = await mgr.run_prompt("ui-sess", "retry after interrupt")
        assert q2 is q

        ctrl2.push(_init_line("sid-new-ui"))
        ctrl2.push(_chunk_line("recovered reply"))
        ctrl2.push(_result_line("recovered reply"))

        # The interrupt's AiError may already be buffered from before run_prompt;
        # use _collect_until_ai_done to skip it and wait for the real turn's AiDone.
        frames = await _collect_until_ai_done(q2, timeout=3.0)
        assert any(isinstance(f, AiDone) for f in frames), (
            f"Expected AiDone after user-interrupt forced respawn: "
            f"{[type(f).__name__ for f in frames]}"
        )


# ─────────────────────────────────────────────
# Test 3: clear_session_id preserves other metadata
# ─────────────────────────────────────────────

def test_clear_session_id_preserves_metadata(tmp_path, monkeypatch):
    """clear_session_id resets session_id to '' but keeps agent/cwd/mode/model."""
    monkeypatch.setattr(store, "SESSIONS_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(store, "BRIDGE_DIR", tmp_path)

    store.upsert_session("meta-sess", "original-sid",
                         agent="claude", cwd="/some/path", mode="act", model="sonnet")
    entry_before = store.get_session("meta-sess")
    assert entry_before["session_id"] == "original-sid"

    store.clear_session_id("meta-sess")

    entry_after = store.get_session("meta-sess")
    assert entry_after["session_id"] == "", "session_id must be cleared to empty string"
    assert entry_after["agent"] == "claude", "agent must be preserved"
    assert entry_after["cwd"] == "/some/path", "cwd must be preserved"
    assert entry_after["mode"] == "act", "mode must be preserved"
    assert entry_after["model"] == "sonnet", "model must be preserved"


def test_clear_session_id_noop_for_missing_session(tmp_path, monkeypatch):
    """clear_session_id on a nonexistent session does not crash."""
    monkeypatch.setattr(store, "SESSIONS_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(store, "BRIDGE_DIR", tmp_path)
    store.clear_session_id("nonexistent")  # must not raise


# ─────────────────────────────────────────────
# Test 4: No duplicate AiError when hard-cap fires (post-exit suppression)
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_no_duplicate_ai_error_after_hard_cap(monkeypatch):
    """Exactly one AiError reaches the queue when the hard-cap fires and the proc exits.

    Before the fix, continuous_reader emitted a second AiError after the proc
    exited (post-exit path), in addition to the one from the watchdog.  This
    test confirms only one AiError arrives.
    """
    monkeypatch.setattr(sr, "_WATCHDOG_HEARTBEAT_S", 0.05)
    monkeypatch.setattr(sr, "_WATCHDOG_HARD_CAP_S", 0.1)

    proc, ctrl = _make_proc(pid=5000)

    q: asyncio.Queue = asyncio.Queue()
    turn_done = asyncio.Event()
    # Clear turn_done to simulate an ACTIVE turn (turn is in progress, not idle).
    # The watchdog only counts silence during active turns, so this is required
    # for the hard-cap to fire and for the duplicate-suppression to be tested.
    # turn_done.set() would put the session in idle state; the watchdog would
    # not count and would never fire the hard-cap.

    interrupt_called = []

    def fake_interrupt():
        interrupt_called.append(True)
        # Simulate proc exit (stdout closes) when SIGINT received
        ctrl.close()

    reader_task = asyncio.create_task(
        sr.continuous_reader("dup-sess", proc, q, turn_done,
                             hard_interrupt_fn=fake_interrupt)
    )

    # Wait for hard-cap to fire and proc to exit
    await asyncio.sleep(0.4)
    try:
        await asyncio.wait_for(reader_task, timeout=1.0)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        reader_task.cancel()
        try:
            await reader_task
        except asyncio.CancelledError:
            pass

    error_frames = []
    while not q.empty():
        f = q.get_nowait()
        if isinstance(f, AiError):
            error_frames.append(f)

    assert len(interrupt_called) >= 1, "hard_interrupt_fn must have been called"
    assert len(error_frames) == 1, (
        f"Expected exactly 1 AiError (from watchdog only, not a duplicate from proc exit), "
        f"got {len(error_frames)}: {[f.stderr_tail for f in error_frames]}"
    )
    # The AiError must be the watchdog's (mentions 'stuck' or 'interrupt')
    assert any(
        kw in error_frames[0].stderr_tail.lower()
        for kw in ("stuck", "interrupt", "respawn", "output")
    ), f"Unexpected AiError content: {error_frames[0].stderr_tail!r}"


# ─────────────────────────────────────────────
# Test 5: run_prompt after hard-cap respawn uses empty session_id (no --resume)
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_prompt_after_clear_does_not_resume(tmp_path, monkeypatch):
    """After clear_session_id, run_prompt does not pass --resume to the new proc."""
    monkeypatch.setattr(store, "SESSIONS_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(store, "BRIDGE_DIR", tmp_path)

    # Seed a session_id in the store, then clear it (simulating the hard-cap fix)
    store.upsert_session("no-resume-sess", "stale-sid")
    store.clear_session_id("no-resume-sess")

    spawn_args: list[list] = []
    proc, ctrl = _make_proc(pid=6000)

    async def fake_spawn(*args, **kwargs):
        spawn_args.append(list(args))
        return proc

    with patch("devscope_bridge.session_manager.asyncio.create_subprocess_exec",
               side_effect=fake_spawn):
        await mgr.run_prompt("no-resume-sess", "fresh message")

    assert len(spawn_args) == 1
    assert "--resume" not in spawn_args[0], (
        f"run_prompt must NOT add --resume when session_id is empty, "
        f"got: {spawn_args[0]}"
    )
