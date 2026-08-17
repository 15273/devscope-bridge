# devscope_bridge/tests/test_capability_router.py
"""Tests for capability_router — collector-queue capture and routing."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from devscope_bridge import (
    background_ask,
    background_cursor_context,
    background_cursor_task,
    capability_registry,
    capability_router,
)
from devscope_bridge.models import AiChunk, AskChunk, AskDone, AskStart


async def _happy_backend(name: str, q: asyncio.Queue, task: str) -> None:
    await q.put(AskStart(session=name, question_id="qid1", question=task))
    await q.put(AskChunk(session=name, question_id="qid1", text="Hello "))
    await q.put(AskChunk(session=name, question_id="qid1", text="world"))
    await q.put(AskDone(session=name, question_id="qid1", ok=True))


async def _usage_backend(name: str, q: asyncio.Queue, task: str) -> None:
    await q.put(AskChunk(session=name, question_id="usage", text="_Usage: /ask <q>_"))


async def _rejected_backend(name: str, q: asyncio.Queue, task: str) -> None:
    await q.put(AiChunk(session=name, text="too many scouts"))


async def _hanging_backend(name: str, q: asyncio.Queue, task: str) -> None:
    await asyncio.sleep(60)


@pytest.mark.asyncio
async def test_collect_accumulates_chunks_into_summary_and_detail():
    result = await capability_router._collect(_happy_backend, {}, "s", "t", 5.0, "claude_print")
    assert result["ok"] is True
    assert result["detail"] == "Hello world"
    assert result["summary"] == "Hello world"
    assert result["backend"] == "claude_print"


@pytest.mark.asyncio
async def test_collect_treats_prestart_hint_as_error():
    result = await capability_router._collect(_usage_backend, {}, "s", "", 5.0, "claude_print")
    assert result["ok"] is False
    assert "Usage" in result["error"]


@pytest.mark.asyncio
async def test_collect_treats_ai_chunk_rejection_as_error():
    result = await capability_router._collect(_rejected_backend, {}, "s", "t", 5.0, "cursor_agent")
    assert result["ok"] is False
    assert "too many scouts" in result["error"]


@pytest.mark.asyncio
async def test_collect_times_out_and_cancels_runner():
    result = await capability_router._collect(_hanging_backend, {}, "s", "t", 0.1, "cursor_agent")
    assert result["ok"] is False
    assert "Timed out" in result["error"]


@pytest.mark.asyncio
async def test_invoke_unknown_capability_lists_known_ids():
    result = await capability_router.invoke("nope", "task")
    assert result["ok"] is False
    assert "notion" in result["known"]


@pytest.mark.asyncio
async def test_invoke_unavailable_returns_missing_and_setup_hint():
    async def all_false(cap):
        return {r: False for r in cap.requires}

    with patch.object(capability_registry, "check_requires", new=all_false):
        result = await capability_router.invoke("notion", "task")
    assert result["ok"] is False
    assert result["missing"]
    assert result["setup_hint"]


@pytest.mark.asyncio
async def test_invoke_direct_mcp_redirects_to_native_tools():
    async def all_true(cap):
        return {r: True for r in cap.requires}

    with patch.object(capability_registry, "check_requires", new=all_true):
        result = await capability_router.invoke("gmail", "read my mail")
    assert result["redirect"] is True
    assert "gm_search_threads" in result["summary"]


@pytest.mark.asyncio
async def test_invoke_prefixes_plugin_tasks():
    async def all_true(cap):
        return {r: True for r in cap.requires}

    collect = AsyncMock(return_value={"ok": True})
    with patch.object(capability_registry, "check_requires", new=all_true), \
         patch.object(capability_router, "_collect", new=collect):
        await capability_router.invoke("plugin:linear", "list my issues")
    task_arg = collect.await_args.args[3]
    assert task_arg.startswith("Using the 'linear' plugin/MCP:")


@pytest.mark.asyncio
async def test_run_on_queue_routes_ask_to_run_ask_on_session_queue():
    q = asyncio.Queue()
    with patch.object(background_ask, "run_ask", new=AsyncMock()) as run_ask:
        out = await capability_router.run_on_queue("parallel_ask", "why?", "sess", q)
    assert out is None
    run_ask.assert_awaited_once_with("sess", q, "why?")


@pytest.mark.asyncio
async def test_run_on_queue_routes_cursor_task_unmodified():
    q = asyncio.Queue()
    with patch.object(background_cursor_task, "run_cursor_task", new=AsyncMock()) as run_task:
        await capability_router.run_on_queue("cursor_plugins", "list notion tasks", "sess", q)
    run_task.assert_awaited_once_with("sess", q, "list notion tasks")


@pytest.mark.asyncio
async def test_run_on_queue_returns_scout_forward_queue():
    q = asyncio.Queue()
    forward_q = asyncio.Queue()
    scout = AsyncMock(return_value=forward_q)
    with patch.object(background_cursor_context, "run_cursor_context", new=scout):
        out = await capability_router.run_on_queue("codebase_scout", "map auth", "sess", q)
    assert out is forward_q
    scout.assert_awaited_once_with("sess", q, "map auth")
