"""Tests for Cursor stop/interrupt and serial turn queue."""

import asyncio
import time
from unittest.mock import patch

import pytest

import devscope_bridge.session_store as store
from devscope_bridge import session_manager_cursor as cursor_mod
from devscope_bridge.models import AiDone, AiError, TurnState


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "SESSIONS_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(store, "BRIDGE_DIR", tmp_path)


@pytest.fixture(autouse=True)
def reset_cursor_globals():
    yield
    for name in list(cursor_mod._cursor_workers):
        cursor_mod.shutdown_cursor_session(name)


class _FakeProc:
    def __init__(self) -> None:
        self.pid = 4242
        self._killed = False

    def poll(self):
        return -9 if self._killed else None

    def kill(self) -> None:
        self._killed = True


def _interruptible_slow_blocking(prompt, prior, cwd, mode, model, loop, q, session_name):
    proc = _FakeProc()
    cursor_mod._cursor_current_proc[session_name] = proc
    try:
        while not proc._killed:
            time.sleep(0.02)
        asyncio.run_coroutine_threadsafe(
            q.put(AiError(session=session_name, exit_code=-9, stderr_tail="[bridge] Turn stopped (SIGKILL)")),
            loop,
        ).result(timeout=2)
        asyncio.run_coroutine_threadsafe(
            q.put(TurnState(session=session_name, running=False)),
            loop,
        ).result(timeout=2)
    finally:
        cursor_mod._cursor_current_proc.pop(session_name, None)


def _fast_blocking(prompt, prior, cwd, mode, model, loop, q, session_name):
    asyncio.run_coroutine_threadsafe(
        q.put(AiDone(session=session_name, exit_code=0)),
        loop,
    ).result(timeout=2)
    asyncio.run_coroutine_threadsafe(
        q.put(TurnState(session=session_name, running=False)),
        loop,
    ).result(timeout=2)


@pytest.mark.asyncio
async def test_interrupt_kills_hung_cursor_and_drains_queued_turns():
    """B4: Stop must cancel BOTH the in-flight turn AND anything queued
    behind it. The old behavior — queued turns still started right after
    Stop killed only the current subprocess — was cursor RC-6 ("Stop that
    doesn't stop"); this asserts the fixed behavior instead of the bug."""
    calls: list[str] = []

    def _blocking(prompt, prior, cwd, mode, model, loop, q, session_name):
        calls.append(prompt)
        if prompt == "first":
            _interruptible_slow_blocking(prompt, prior, cwd, mode, model, loop, q, session_name)
        else:
            _fast_blocking(prompt, prior, cwd, mode, model, loop, q, session_name)

    with patch.object(cursor_mod, "_run_cursor_streaming_blocking", side_effect=_blocking):
        q = await cursor_mod.dispatch_cursor("sess-a", "first", None, "/tmp")
        await cursor_mod.dispatch_cursor("sess-a", "second", None, "/tmp")

        await asyncio.sleep(0.1)
        state_before = cursor_mod.get_session_state("sess-a")
        assert state_before["queued_turns"] == 1
        assert cursor_mod.interrupt_cursor("sess-a") is True

        saw_error = False
        async with asyncio.timeout(5.0):
            while not saw_error:
                frame = await q.get()
                if isinstance(frame, AiError):
                    saw_error = True

        # Give a wrongly-still-queued "second" turn a chance to fire before
        # asserting it never did.
        await asyncio.sleep(0.2)

    assert calls == ["first"]


@pytest.mark.asyncio
async def test_interrupt_returns_false_when_idle():
    assert cursor_mod.interrupt_cursor("no-such-session") is False


@pytest.mark.asyncio
async def test_serial_queue_runs_two_turns():
    prompts: list[str] = []

    def _record(prompt, prior, cwd, mode, model, loop, q, session_name):
        prompts.append(prompt)
        _fast_blocking(prompt, prior, cwd, mode, model, loop, q, session_name)

    with patch.object(cursor_mod, "_run_cursor_streaming_blocking", side_effect=_record):
        q = await cursor_mod.dispatch_cursor("sess-b", "one", None, "/tmp")
        await cursor_mod.dispatch_cursor("sess-b", "two", None, "/tmp")

        done_count = 0
        async with asyncio.timeout(5.0):
            while done_count < 2:
                frame = await q.get()
                if isinstance(frame, AiDone):
                    done_count += 1

    assert prompts == ["one", "two"]
