"""Tests for cursor-agent turn watchdog (silence hard-cap)."""

import asyncio
import time
from unittest.mock import patch

import pytest

import devscope_bridge.session_reader as sr
import devscope_bridge.session_store as store
from devscope_bridge import session_manager_cursor as cursor_mod
from devscope_bridge.models import AgentActivity, AiError, TurnState


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "SESSIONS_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(store, "BRIDGE_DIR", tmp_path)


@pytest.fixture(autouse=True)
def reset_cursor_globals():
    yield
    for name in list(cursor_mod._cursor_workers):
        cursor_mod.shutdown_cursor_session(name)


class _SilentProc:
    """Simulates cursor-agent that never writes stdout until killed."""

    def __init__(self) -> None:
        self.pid = 9001
        self._killed = False

    def poll(self):
        return -9 if self._killed else None

    def kill(self) -> None:
        self._killed = True

    @property
    def returncode(self):
        return -9 if self._killed else None

    @property
    def stdout(self):
        return None

    @property
    def stderr(self):
        return None


def _hang_until_killed(prompt, prior, cwd, mode, model, loop, q, session_name):
    proc = _SilentProc()
    cursor_mod._cursor_current_proc[session_name] = proc
    try:
        while not proc._killed:
            time.sleep(0.05)
        reason = cursor_mod.cursor_watchdog.consume_kill_reason(session_name)
        if reason:
            asyncio.run_coroutine_threadsafe(
                q.put(AiError(session=session_name, exit_code=-1, stderr_tail=reason)),
                loop,
            ).result(timeout=2)
            asyncio.run_coroutine_threadsafe(
                q.put(TurnState(session=session_name, running=False)),
                loop,
            ).result(timeout=2)
    finally:
        cursor_mod._cursor_current_proc.pop(session_name, None)


@pytest.mark.asyncio
async def test_cursor_watchdog_emits_heartbeat_then_hard_cap(monkeypatch):
    monkeypatch.setattr(sr, "_WATCHDOG_HEARTBEAT_S", 0.15)
    monkeypatch.setattr(sr, "_WATCHDOG_MEDIC_S", 9999.0)
    monkeypatch.setattr(sr, "_WATCHDOG_HARD_CAP_S", 0.45)
    monkeypatch.setattr(sr, "_WATCHDOG_TURN_WALL_MEDIC_S", 9999.0)
    monkeypatch.setattr(sr, "_WATCHDOG_TURN_WALL_CAP_S", 9999.0)

    with patch.object(cursor_mod, "_run_cursor_streaming_blocking", side_effect=_hang_until_killed):
        q = await cursor_mod.dispatch_cursor("wd-sess", "hang", None, "/tmp")

        saw_heartbeat = False
        saw_error = False
        async with asyncio.timeout(5.0):
            while not saw_error:
                frame = await q.get()
                if isinstance(frame, AgentActivity) and "still working" in frame.label:
                    saw_heartbeat = True
                if isinstance(frame, AiError):
                    assert "silent" in frame.stderr_tail or "turn stopped" in frame.stderr_tail
                    saw_error = True

        assert saw_heartbeat
        assert saw_error
