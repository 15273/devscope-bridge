# devscope_bridge/tests/test_cursor_task_command.py
"""Tests for /cursor-task (background_cursor_task)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from devscope_bridge import background_cursor_task


@pytest.mark.asyncio
async def test_cursor_task_empty_shows_usage():
    q = AsyncMock()
    await background_cursor_task.run_cursor_task("my-chat", q, "   ")
    assert q.put.await_count >= 1
    first = q.put.await_args_list[0].args[0]
    assert "cursor-task" in getattr(first, "text", "")


@pytest.mark.asyncio
async def test_cursor_task_emits_ask_start():
    q = AsyncMock()

    async def fake_thread(fn, *_args, **_kwargs):
        if fn is background_cursor_task._mcp_list_status:
            return {}
        return None

    with patch.object(background_cursor_task.asyncio, "to_thread", new=fake_thread):
        await background_cursor_task.run_cursor_task("my-chat", q, "fetch notion tasks")

    kinds = [getattr(call.args[0], "kind", None) for call in q.put.await_args_list if hasattr(call.args[0], "kind")]
    assert "cursor_task" in kinds


@pytest.mark.asyncio
async def test_cursor_task_warns_when_notion_missing():
    q = AsyncMock()

    async def fake_thread(fn, *_args, **_kwargs):
        if fn is background_cursor_task._mcp_list_status:
            return {"browser-control": "ready"}
        return None

    with patch.object(background_cursor_task.asyncio, "to_thread", new=fake_thread):
        await background_cursor_task.run_cursor_task("my-chat", q, "list my notion tasks")

    texts = [getattr(call.args[0], "text", "") for call in q.put.await_args_list]
    assert any("Notion is not connected" in t for t in texts)
