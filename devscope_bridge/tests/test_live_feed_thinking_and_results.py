"""
test_live_feed_thinking_and_results.py

Tests for the richer live-feed frames added to dispatch_event:

Thinking blocks:
1. stream_event content_block_start with type="thinking" emits
   AgentActivity(label="Thinking")
2. stream_event content_block_delta with type="thinking_delta" emits
   AgentActivity(label="Thinking", detail=<short snippet>)
3. thinking_delta snippet is capped at 60 chars
4. Non-thinking content_block_start does NOT emit Thinking activity
5. text_delta still emits AiChunk (no regression)

Tool result summaries:
6. user event with tool_result for a known Bash tool emits AgentActivity
   with label="Bash done" and a short detail
7. user event with tool_result for an unknown tool_use_id still emits
   AgentActivity(label="tool done")
8. tool_result for a Task (sub-agent) is NOT double-emitted as a summary
9. is_error=True tool_result detail starts with "error:"
10. Multi-line Bash output produces line-count summary
11. Empty tool_result content produces detail="ok"
12. tool_result content as list of text blocks is flattened for summary
13. Pending tool call tracking is cleared on turn end (result event)
14. Multiple tool results in one user event → one summary per result
15. tool_use_id registration from assistant event enables name resolution
"""

import asyncio
import pytest

from devscope_bridge import session_reader, session_store, sub_agent_tracker
from devscope_bridge import _live_feed_helpers as _lfh
from devscope_bridge.models import AgentActivity, AiChunk, AiDone


# ─────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clean_state(tmp_path, monkeypatch):
    """Reset module-level state before/after each test.

    Isolates session_store's transcript dir so dispatch_event's `result`
    handler (A9: it now persists accumulated assistant text via
    append_bridge_turn) never writes to the real ~/.dev-bridge on disk —
    several tests here use the generic session name "s".
    """
    monkeypatch.setattr(session_store, "BRIDGE_DIR", tmp_path)
    monkeypatch.setattr(session_store, "BRIDGE_TRANSCRIPTS_DIR", tmp_path / "chat-transcripts")
    sub_agent_tracker._in_flight.clear()
    _lfh._pending_tool_calls.clear()
    session_reader._assistant_text_accum.clear()
    yield
    sub_agent_tracker._in_flight.clear()
    _lfh._pending_tool_calls.clear()
    session_reader._assistant_text_accum.clear()


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _stream_event(inner: dict) -> dict:
    return {"type": "stream_event", "event": inner}


def _content_block_start(block_type: str, name: str | None = None) -> dict:
    block: dict = {"type": block_type}
    if name is not None:
        block["name"] = name
    ev: dict = {"type": "content_block_start", "index": 0, "content_block": block}
    return ev


def _content_block_delta(delta_type: str, **kwargs) -> dict:
    delta: dict = {"type": delta_type, **kwargs}
    return {"type": "content_block_delta", "index": 0, "delta": delta}


def _text_delta(text: str) -> dict:
    return _content_block_delta("text_delta", text=text)


def _thinking_start_event() -> dict:
    return _stream_event(_content_block_start("thinking"))


def _thinking_delta_event(snippet: str) -> dict:
    return _stream_event(_content_block_delta("thinking_delta", thinking=snippet))


def _assistant_event_with_tool(
    tool_id: str, tool_name: str, command: str = "ls -la"
) -> dict:
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": tool_id,
                    "name": tool_name,
                    "input": {"command": command} if tool_name == "Bash" else {"file_path": command},
                }
            ],
        },
    }


def _user_tool_result_event(
    tool_use_id: str,
    content: object = "output",
    is_error: bool = False,
) -> dict:
    return {
        "type": "user",
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "is_error": is_error,
                    "content": content,
                }
            ],
        },
    }


def _result_event() -> dict:
    return {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": "ok",
        "permission_denials": [],
        "usage": {},
        "total_cost_usd": 0,
        "duration_ms": 0,
    }


async def _drain(q: asyncio.Queue) -> list:
    frames = []
    while True:
        try:
            frames.append(q.get_nowait())
        except asyncio.QueueEmpty:
            break
    return frames


# ─────────────────────────────────────────────
# Thinking block tests
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_thinking_block_start_emits_activity():
    """content_block_start with type=thinking → AgentActivity(label='Thinking')."""
    q: asyncio.Queue = asyncio.Queue()
    await session_reader.dispatch_event(
        "s", _thinking_start_event(), q, is_first_message=False
    )
    frames = await _drain(q)

    thinking = [f for f in frames if isinstance(f, AgentActivity) and f.label == "Thinking"]
    assert len(thinking) == 1, f"Expected 1 Thinking activity, got: {frames}"
    assert thinking[0].detail is None


@pytest.mark.asyncio
async def test_thinking_delta_emits_activity_with_detail():
    """thinking_delta → AgentActivity(label='Thinking', detail=<snippet>)."""
    q: asyncio.Queue = asyncio.Queue()
    await session_reader.dispatch_event(
        "s", _thinking_delta_event("I need to check the file structure first"),
        q, is_first_message=False
    )
    frames = await _drain(q)

    thinking = [f for f in frames if isinstance(f, AgentActivity) and f.label == "Thinking"]
    assert len(thinking) == 1, f"Expected 1 Thinking activity, got: {frames}"
    assert "check the file structure" in (thinking[0].detail or "")


@pytest.mark.asyncio
async def test_thinking_delta_snippet_capped_at_60():
    """thinking_delta snippet is capped at 60 chars."""
    q: asyncio.Queue = asyncio.Queue()
    long_text = "A" * 100
    await session_reader.dispatch_event(
        "s", _thinking_delta_event(long_text), q, is_first_message=False
    )
    frames = await _drain(q)

    thinking = [f for f in frames if isinstance(f, AgentActivity) and f.label == "Thinking"]
    assert len(thinking) == 1
    assert len(thinking[0].detail or "") <= 60


@pytest.mark.asyncio
async def test_non_thinking_content_block_start_no_thinking_activity():
    """content_block_start with type=text does NOT emit Thinking activity."""
    q: asyncio.Queue = asyncio.Queue()
    await session_reader.dispatch_event(
        "s", _stream_event(_content_block_start("text")), q, is_first_message=False
    )
    frames = await _drain(q)

    thinking = [f for f in frames if isinstance(f, AgentActivity) and f.label == "Thinking"]
    assert len(thinking) == 0, f"Unexpected Thinking activity: {thinking}"


@pytest.mark.asyncio
async def test_text_delta_still_emits_ai_chunk():
    """text_delta in stream_event still produces AiChunk (no regression)."""
    q: asyncio.Queue = asyncio.Queue()
    await session_reader.dispatch_event(
        "s", _stream_event(_text_delta("hello world")), q, is_first_message=False
    )
    frames = await _drain(q)

    chunks = [f for f in frames if isinstance(f, AiChunk)]
    assert len(chunks) == 1
    assert chunks[0].text == "hello world"

    thinking = [f for f in frames if isinstance(f, AgentActivity) and f.label == "Thinking"]
    assert len(thinking) == 0, "text_delta must not produce Thinking frames"


# ─────────────────────────────────────────────
# Tool result summary tests
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_bash_tool_result_emits_summary():
    """Bash tool_result emits AgentActivity(label='Bash done', detail=<summary>)."""
    q: asyncio.Queue = asyncio.Queue()
    # Register the tool call first
    await session_reader.dispatch_event(
        "s", _assistant_event_with_tool("tid1", "Bash", "ls -la"), q, is_first_message=False
    )
    await _drain(q)  # clear the tool-use activity frame

    await session_reader.dispatch_event(
        "s", _user_tool_result_event("tid1", "total 8\ndrwxr-xr-x  2 user group 64 May 31 session_reader.py"),
        q, is_first_message=False
    )
    frames = await _drain(q)

    result_frames = [f for f in frames if isinstance(f, AgentActivity) and "done" in f.label]
    assert len(result_frames) == 1, f"Expected 1 summary frame, got: {frames}"
    rf = result_frames[0]
    assert rf.tool == "Bash"
    assert rf.label == "Bash done"
    assert rf.detail is not None


@pytest.mark.asyncio
async def test_unknown_tool_use_id_emits_generic_summary():
    """tool_result for unregistered tool_use_id → AgentActivity(label='tool done')."""
    q: asyncio.Queue = asyncio.Queue()
    # No preceding assistant event — tool_use_id is unknown
    await session_reader.dispatch_event(
        "s", _user_tool_result_event("unknown-tid", "some output"),
        q, is_first_message=False
    )
    frames = await _drain(q)

    result_frames = [f for f in frames if isinstance(f, AgentActivity)]
    assert len(result_frames) == 1
    assert result_frames[0].label == "tool done"
    assert result_frames[0].tool is None


@pytest.mark.asyncio
async def test_task_tool_result_not_double_emitted():
    """tool_result for a Task (sub-agent) is NOT emitted as a regular summary."""
    q: asyncio.Queue = asyncio.Queue()
    # Spawn a sub-agent
    task_block = {
        "type": "tool_use", "id": "task-tid", "name": "Task",
        "input": {"description": "do stuff", "prompt": "do stuff"},
    }
    await session_reader.dispatch_event(
        "s",
        {"type": "assistant", "message": {"role": "assistant", "content": [task_block]}},
        q, is_first_message=False
    )
    await _drain(q)

    # Complete it
    await session_reader.dispatch_event(
        "s", _user_tool_result_event("task-tid", "sub-agent output"),
        q, is_first_message=False
    )
    frames = await _drain(q)

    # Only SubAgent(phase='done') should appear — no AgentActivity summary
    from devscope_bridge.models import SubAgent
    sub_done = [f for f in frames if isinstance(f, SubAgent) and f.phase == "done"]
    assert len(sub_done) == 1

    # The tool_result summary MUST NOT also be emitted for the Task result
    result_summaries = [
        f for f in frames
        if isinstance(f, AgentActivity) and "done" in f.label
    ]
    assert len(result_summaries) == 0, (
        f"Task tool_result must not produce a duplicate summary: {result_summaries}"
    )


@pytest.mark.asyncio
async def test_error_tool_result_detail_starts_with_error():
    """is_error=True tool_result → detail starts with 'error:'."""
    q: asyncio.Queue = asyncio.Queue()
    await session_reader.dispatch_event(
        "s", _assistant_event_with_tool("tid-err", "Bash", "bad cmd"), q, is_first_message=False
    )
    await _drain(q)

    await session_reader.dispatch_event(
        "s", _user_tool_result_event("tid-err", "command not found", is_error=True),
        q, is_first_message=False
    )
    frames = await _drain(q)

    result_frames = [f for f in frames if isinstance(f, AgentActivity) and "done" in f.label]
    assert len(result_frames) == 1
    detail = result_frames[0].detail or ""
    assert detail.startswith("error:"), f"Expected 'error:' prefix, got: {detail!r}"


@pytest.mark.asyncio
async def test_multiline_bash_output_shows_line_count():
    """Multi-line Bash output → detail includes line count."""
    q: asyncio.Queue = asyncio.Queue()
    await session_reader.dispatch_event(
        "s", _assistant_event_with_tool("tid-multi", "Bash", "ls"), q, is_first_message=False
    )
    await _drain(q)

    multiline = "file1.py\nfile2.py\nfile3.py\nfile4.py\nfile5.py"
    await session_reader.dispatch_event(
        "s", _user_tool_result_event("tid-multi", multiline),
        q, is_first_message=False
    )
    frames = await _drain(q)

    result_frames = [f for f in frames if isinstance(f, AgentActivity) and "done" in f.label]
    assert len(result_frames) == 1
    detail = result_frames[0].detail or ""
    # Must mention multiple lines somehow
    assert "line" in detail.lower() or "+" in detail, (
        f"Expected line count in detail for multi-line output, got: {detail!r}"
    )


@pytest.mark.asyncio
async def test_empty_tool_result_content_produces_ok():
    """Empty tool_result content → detail='ok'."""
    q: asyncio.Queue = asyncio.Queue()
    await session_reader.dispatch_event(
        "s", _user_tool_result_event("tid-empty", ""), q, is_first_message=False
    )
    frames = await _drain(q)

    result_frames = [f for f in frames if isinstance(f, AgentActivity)]
    assert len(result_frames) == 1
    assert result_frames[0].detail == "ok"


@pytest.mark.asyncio
async def test_list_content_blocks_flattened_for_summary():
    """tool_result content as list of text blocks is flattened for the summary."""
    q: asyncio.Queue = asyncio.Queue()
    content_list = [
        {"type": "text", "text": "part one"},
        {"type": "text", "text": " part two"},
    ]
    await session_reader.dispatch_event(
        "s", _user_tool_result_event("tid-list", content_list),
        q, is_first_message=False
    )
    frames = await _drain(q)

    result_frames = [f for f in frames if isinstance(f, AgentActivity)]
    assert len(result_frames) == 1
    detail = result_frames[0].detail or ""
    assert "part one" in detail
    assert "part two" in detail


@pytest.mark.asyncio
async def test_pending_tool_calls_cleared_on_turn_end():
    """After a result event, pending tool call tracking is cleared."""
    q: asyncio.Queue = asyncio.Queue()
    # Register a tool call
    await session_reader.dispatch_event(
        "s", _assistant_event_with_tool("tid-clear", "Bash", "echo hi"), q, is_first_message=False
    )
    await _drain(q)

    # Verify it was registered
    assert "s" in _lfh._pending_tool_calls
    assert "tid-clear" in _lfh._pending_tool_calls["s"]

    # Turn ends
    await session_reader.dispatch_event("s", _result_event(), q, is_first_message=False)
    await _drain(q)

    # Pending state must be cleared
    assert "s" not in _lfh._pending_tool_calls or not _lfh._pending_tool_calls.get("s")


@pytest.mark.asyncio
async def test_multiple_tool_results_one_frame_each():
    """Multiple tool_result blocks in one user event → one summary frame each."""
    q: asyncio.Queue = asyncio.Queue()
    # Register two tool calls
    await session_reader.dispatch_event(
        "s",
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": "tid-a", "name": "Bash",
                     "input": {"command": "ls"}},
                    {"type": "tool_use", "id": "tid-b", "name": "Read",
                     "input": {"file_path": "foo.py"}},
                ],
            },
        },
        q, is_first_message=False
    )
    await _drain(q)

    # Both results in one user event
    user_event = {
        "type": "user",
        "message": {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "tid-a",
                 "is_error": False, "content": "file-a.txt"},
                {"type": "tool_result", "tool_use_id": "tid-b",
                 "is_error": False, "content": "class Foo: ..."},
            ],
        },
    }
    await session_reader.dispatch_event("s", user_event, q, is_first_message=False)
    frames = await _drain(q)

    result_frames = [f for f in frames if isinstance(f, AgentActivity) and "done" in f.label]
    assert len(result_frames) == 2, f"Expected 2 summary frames, got: {result_frames}"
    tools = {f.tool for f in result_frames}
    assert "Bash" in tools
    assert "Read" in tools


@pytest.mark.asyncio
async def test_assistant_event_registers_tool_use_ids():
    """assistant event with tool_use blocks registers tool_use_id → name in _pending_tool_calls."""
    q: asyncio.Queue = asyncio.Queue()
    await session_reader.dispatch_event(
        "sess-reg",
        _assistant_event_with_tool("my-tid", "Read", "/tmp/foo.py"),
        q, is_first_message=False
    )
    await _drain(q)

    assert "sess-reg" in _lfh._pending_tool_calls
    assert _lfh._pending_tool_calls["sess-reg"].get("my-tid") == {
        "name": "Read",
        "input": {"file_path": "/tmp/foo.py"},
    }


# ─────────────────────────────────────────────
# _tool_result_summary unit tests (pure functions)
# ─────────────────────────────────────────────

def test_flatten_content_str():
    assert _lfh._flatten_content("hello") == "hello"


def test_flatten_content_list():
    result = _lfh._flatten_content([
        {"type": "text", "text": "a"},
        {"type": "text", "text": "b"},
    ])
    assert "a" in result and "b" in result


def test_flatten_content_none():
    assert _lfh._flatten_content(None) == ""


def test_tool_result_summary_error():
    s = _lfh._tool_result_summary("Bash", "command not found", is_error=True)
    assert s.startswith("error:")
    assert "command not found" in s


def test_tool_result_summary_browser_503_not_truncated():
    detail = (
        "Browser client not connected (session='google_console', connected=['mom']). "
        "Reload DevScope unpacked from extension/dist"
    )
    s = _lfh._tool_result_summary("mcp__browser-control__browser_navigate", detail, is_error=True)
    assert detail in s


def test_tool_result_summary_empty_ok():
    s = _lfh._tool_result_summary("Read", "", is_error=False)
    assert s == "ok"


def test_tool_result_summary_bash_multiline():
    content = "\n".join(f"line{i}" for i in range(10))
    s = _lfh._tool_result_summary("Bash", content, is_error=False)
    assert "line" in s.lower() or "+" in s
    assert len(s) <= 80


def test_tool_result_summary_single_line_bash():
    s = _lfh._tool_result_summary("Bash", "hello", is_error=False)
    assert "hello" in s


def test_tool_result_summary_non_bash_truncates():
    long_output = "x" * 200
    s = _lfh._tool_result_summary("Read", long_output, is_error=False)
    assert len(s) <= 80
