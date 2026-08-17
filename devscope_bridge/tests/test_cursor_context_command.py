"""Tests for /cursor-ctx (background_cursor_context)."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

import devscope_bridge.background_cursor_context as bcctx


@pytest.fixture(autouse=True)
def clean_state():
    bcctx._active_scouts.clear()
    yield
    bcctx._active_scouts.clear()


def _drain(q: asyncio.Queue) -> list:
    items = []
    while not q.empty():
        items.append(q.get_nowait())
    return items


@pytest.mark.asyncio
async def test_cursor_ctx_rejects_non_claude_session(monkeypatch):
    monkeypatch.setattr(
        bcctx.session_store,
        "get_session",
        lambda _name: {"agent": "cursor", "cwd": "/tmp"},
    )
    q: asyncio.Queue = asyncio.Queue()
    result = await bcctx.run_cursor_context("s", q, "find auth module")
    assert result is None
    frames = _drain(q)
    assert any(getattr(f, "text", "").find("Claude") >= 0 for f in frames if hasattr(f, "text"))


@pytest.mark.asyncio
async def test_cursor_ctx_empty_task_shows_usage(monkeypatch):
    monkeypatch.setattr(
        bcctx.session_store,
        "get_session",
        lambda _name: {"agent": "claude", "cwd": "/tmp"},
    )
    q: asyncio.Queue = asyncio.Queue()
    await bcctx.run_cursor_context("s", q, "   ")
    frames = _drain(q)
    assert any("cursor-ctx" in getattr(f, "text", "") for f in frames if hasattr(f, "text"))


@pytest.mark.asyncio
async def test_cursor_ctx_forwards_to_claude_on_success(monkeypatch):
    monkeypatch.setattr(
        bcctx.session_store,
        "get_session",
        lambda _name: {"agent": "claude", "cwd": "/tmp"},
    )
    monkeypatch.setattr(bcctx, "_session_cwd", lambda _name: "/tmp")
    q: asyncio.Queue = asyncio.Queue()
    forward_q: asyncio.Queue = asyncio.Queue()

    def fake_run(*_args, **_kwargs):
        return 0, ['{"type":"text_delta","text":"## Summary\\nauth in backend/api"}'], ""

    with patch.object(bcctx, "_run_cursor_streaming", fake_run):
        mock_run_prompt = AsyncMock(return_value=forward_q)
        with patch.object(bcctx.session_manager, "run_prompt", mock_run_prompt):
            with patch.object(bcctx.session_manager, "reset_idle"):
                result = await bcctx.run_cursor_context("s", q, "fix login bug")

    assert result is forward_q
    frames = _drain(q)
    kinds = [type(f).__name__ for f in frames]
    assert "AskStart" in kinds
    assert "AskDone" in kinds
    ask_start = next(f for f in frames if type(f).__name__ == "AskStart")
    assert ask_start.kind == "cursor_ctx"
    mock_run_prompt.assert_awaited_once()
    combined = mock_run_prompt.await_args.args[1]
    assert "Codebase context" in combined
    assert "fix login bug" in combined
