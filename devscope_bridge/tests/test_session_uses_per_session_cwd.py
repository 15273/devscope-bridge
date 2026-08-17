"""
test_session_uses_per_session_cwd.py

Verify that run_prompt passes the per-session cwd (not the global DEFAULT_CWD)
to asyncio.create_subprocess_exec for Claude sessions.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import devscope_bridge.session_store as store
import devscope_bridge.session_manager as mgr


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "SESSIONS_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(store, "BRIDGE_DIR", tmp_path)
    # Clear in-flight sessions
    mgr._sessions.clear()
    yield
    mgr._sessions.clear()


class _EmptyAsyncIterator:
    """Async iterator that yields nothing — simulates an immediately-closed stdout."""

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


def _make_fake_proc():
    """Return a mock asyncio.subprocess.Process that drains immediately."""
    proc = MagicMock()
    proc.pid = 99999
    proc.returncode = None  # process is still running

    proc.stdout = _EmptyAsyncIterator()

    proc.stderr = AsyncMock()
    proc.stderr.read = AsyncMock(return_value=b"")

    async def _wait():
        return 0

    proc.wait = _wait

    # stdin: supports write() + drain() for persistent process
    proc.stdin = MagicMock()
    proc.stdin.write = MagicMock()
    proc.stdin.drain = AsyncMock()

    return proc


@pytest.mark.asyncio
async def test_claude_session_uses_per_session_cwd(tmp_path):
    """The cwd passed to create_subprocess_exec matches the session's stored cwd."""
    custom_cwd = str(tmp_path / "my_project")
    tmp_path.joinpath("my_project").mkdir()

    store.create_session_metadata("cwd-test", "claude", custom_cwd)

    captured_kwargs: list[dict] = []

    async def fake_create_subprocess_exec(*args, **kwargs):
        captured_kwargs.append(kwargs)
        return _make_fake_proc()

    with patch("devscope_bridge.session_manager.asyncio.create_subprocess_exec",
               side_effect=fake_create_subprocess_exec):
        q = await mgr.run_prompt("cwd-test", "hello")

    assert len(captured_kwargs) == 1
    assert captured_kwargs[0]["cwd"] == custom_cwd


@pytest.mark.asyncio
async def test_unknown_session_falls_back_to_default_cwd():
    """A session not in the store uses DEFAULT_CWD."""
    captured_kwargs: list[dict] = []

    async def fake_create_subprocess_exec(*args, **kwargs):
        captured_kwargs.append(kwargs)
        return _make_fake_proc()

    with patch("devscope_bridge.session_manager.asyncio.create_subprocess_exec",
               side_effect=fake_create_subprocess_exec):
        q = await mgr.run_prompt("no-metadata-session", "hi")

    assert len(captured_kwargs) == 1
    assert captured_kwargs[0]["cwd"] == mgr.DEFAULT_CWD
