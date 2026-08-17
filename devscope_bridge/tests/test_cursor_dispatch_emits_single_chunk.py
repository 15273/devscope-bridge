"""
test_cursor_dispatch_emits_single_chunk.py

Verify the Cursor dispatch path:
- Emits SessionReady + AiChunk(s) + AiDone on success.
- Emits AiError (no AiChunk) when the subprocess returns non-zero.
- Emits AiError when the Cursor binary is not found.
"""

import asyncio
import json
import pytest
from unittest.mock import patch

from devscope_bridge.models import AiChunk, AiDone, AiError, SessionReady
from devscope_bridge import session_manager_cursor as cursor_mod
from devscope_bridge.tests.test_cursor_streaming import _make_fake_blocking


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    import devscope_bridge.session_store as store
    monkeypatch.setattr(store, "SESSIONS_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(store, "BRIDGE_DIR", tmp_path)


async def _drain_until_terminal(q: asyncio.Queue, timeout: float = 5.0) -> list:
    """Collect frames until AiDone or AiError arrives, or timeout."""
    frames = []
    try:
        async with asyncio.timeout(timeout):
            while True:
                frame = await q.get()
                frames.append(frame)
                if isinstance(frame, (AiDone, AiError)):
                    break
    except TimeoutError:
        pass
    return frames


@pytest.mark.asyncio
async def test_success_emits_session_ready_chunks_and_done():
    """stream-json line → individual AiChunk; SessionReady + AiDone on success."""
    canned_line = json.dumps({"type": "text_delta", "text": "Here is the answer from Cursor."})

    with patch.object(
        cursor_mod,
        "_run_cursor_streaming_blocking",
        side_effect=_make_fake_blocking(0, [canned_line]),
    ):
        q = await cursor_mod.dispatch_cursor("test-s", "do something", None, "/tmp")
        frames = await _drain_until_terminal(q)

    types = [type(f) for f in frames]
    assert SessionReady in types, f"Expected SessionReady, got: {types}"
    chunks = [f for f in frames if isinstance(f, AiChunk)]
    assert len(chunks) >= 1, f"Expected AiChunk(s), got {len(chunks)}: {frames}"
    assert any(isinstance(f, AiDone) for f in frames), "Expected AiDone"
    assert not any(isinstance(f, AiError) for f in frames), "Unexpected AiError"


@pytest.mark.asyncio
async def test_nonzero_exit_emits_error_no_chunk():
    with patch.object(
        cursor_mod,
        "_run_cursor_streaming_blocking",
        side_effect=_make_fake_blocking(1, [], "something went wrong"),
    ):
        q = await cursor_mod.dispatch_cursor("test-fail", "bad prompt", None, "/tmp")
        frames = await _drain_until_terminal(q)

    assert any(isinstance(f, AiError) for f in frames), "Expected AiError"
    assert not any(isinstance(f, AiChunk) for f in frames), "Expected no AiChunk on error"
    assert not any(isinstance(f, AiDone) for f in frames), "Expected no AiDone on error"


@pytest.mark.asyncio
async def test_missing_binary_emits_ai_error():
    def _raise(prompt, prior, cwd, mode, model, loop, q, session_name):
        raise FileNotFoundError("cursor-agent not found")

    with patch.object(cursor_mod, "_run_cursor_streaming_blocking", side_effect=_raise):
        q = await cursor_mod.dispatch_cursor("test-missing", "hello", None, "/tmp")
        frames = await _drain_until_terminal(q)

    errors = [f for f in frames if isinstance(f, AiError)]
    assert len(errors) == 1
    assert "not found" in errors[0].stderr_tail.lower() or "cursor" in errors[0].stderr_tail.lower()


@pytest.mark.asyncio
async def test_empty_stdout_no_chunk_emitted():
    """Empty stdout: SessionReady + AiDone but no AiChunk."""
    with patch.object(
        cursor_mod,
        "_run_cursor_streaming_blocking",
        side_effect=_make_fake_blocking(0, []),
    ):
        q = await cursor_mod.dispatch_cursor("test-empty", "quiet", None, "/tmp")
        frames = await _drain_until_terminal(q)

    assert not any(isinstance(f, AiChunk) for f in frames)
    assert any(isinstance(f, AiDone) for f in frames)
