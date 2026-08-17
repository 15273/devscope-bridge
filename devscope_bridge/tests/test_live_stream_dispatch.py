"""dispatch_event emits turn-tagged chunks, thinking chunks, and turn results."""
import asyncio
import pytest

from devscope_bridge import session_reader
from devscope_bridge.models import AiChunk, AiDone, ThinkingChunk, TurnResult, TurnState


async def _drain(q: asyncio.Queue) -> list:
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


def _text_delta_event(text: str, index: int = 0) -> dict:
    return {"type": "stream_event",
            "event": {"type": "content_block_delta", "index": index,
                      "delta": {"type": "text_delta", "text": text}}}


def _block_start_event(index: int, block_type: str = "text") -> dict:
    return {"type": "stream_event",
            "event": {"type": "content_block_start", "index": index,
                      "content_block": {"type": block_type}}}


def _thinking_delta_event(text: str) -> dict:
    return {"type": "stream_event",
            "event": {"type": "content_block_delta", "index": 0,
                      "delta": {"type": "thinking_delta", "thinking": text}}}


@pytest.mark.asyncio
async def test_ai_chunk_carries_turn_and_block(monkeypatch):
    session_reader.set_current_turn_id("s", "turn-1")
    q = asyncio.Queue()
    await session_reader.dispatch_event("s", _block_start_event(0), q, is_first_message=False)
    await session_reader.dispatch_event("s", _text_delta_event("hello"), q, is_first_message=False)
    frames = await _drain(q)
    chunk = next(f for f in frames if isinstance(f, AiChunk))
    # block_index is a per-session monotonic counter bumped on every text
    # content_block_start (NOT the raw CLI index, which restarts per assistant
    # message) — the first text block of a fresh session counts from 1.
    assert chunk.turn_id == "turn-1" and chunk.block_index == 1


@pytest.mark.asyncio
async def test_new_text_block_bumps_block_index():
    session_reader.set_current_turn_id("s2", "turn-2")
    q = asyncio.Queue()
    await session_reader.dispatch_event("s2", _block_start_event(0), q, is_first_message=False)
    await session_reader.dispatch_event("s2", _text_delta_event("a", 0), q, is_first_message=False)
    await session_reader.dispatch_event("s2", _block_start_event(2), q, is_first_message=False)
    await session_reader.dispatch_event("s2", _text_delta_event("b", 2), q, is_first_message=False)
    chunks = [f for f in await _drain(q) if isinstance(f, AiChunk)]
    # The counter is turn-unique, not the raw (CLI-restartable) stream index —
    # a second text content_block_start always bumps it, even if the CLI
    # happens to reuse a lower raw index.
    assert [c.block_index for c in chunks] == [1, 2]


@pytest.mark.asyncio
async def test_thinking_delta_emits_thinking_chunk():
    session_reader.set_current_turn_id("s3", "turn-3")
    q = asyncio.Queue()
    await session_reader.dispatch_event("s3", _thinking_delta_event("pondering…"), q, is_first_message=False)
    frames = await _drain(q)
    tc = next(f for f in frames if isinstance(f, ThinkingChunk))
    assert tc.text == "pondering…" and tc.turn_id == "turn-3"


@pytest.mark.asyncio
async def test_result_emits_turn_result_before_done():
    session_reader.set_current_turn_id("s4", "turn-4")
    q = asyncio.Queue()
    result_event = {"type": "result", "subtype": "success", "is_error": False,
                    "duration_ms": 2500, "total_cost_usd": 0.034,
                    "usage": {"input_tokens": 1200, "output_tokens": 480},
                    "model": "claude-sonnet-5"}
    done = await session_reader.dispatch_event("s4", result_event, q, is_first_message=False)
    assert done is True
    frames = await _drain(q)
    tr = next(f for f in frames if isinstance(f, TurnResult))
    assert (tr.turn_id, tr.duration_ms, tr.output_tokens, tr.model) == ("turn-4", 2500, 480, "claude-sonnet-5")
    ai_done = next(f for f in frames if isinstance(f, AiDone))
    assert ai_done.turn_id == "turn-4"
    ts = next(f for f in frames if isinstance(f, TurnState))
    assert ts.turn_id == "turn-4"
    assert frames.index(tr) < frames.index(ai_done)


@pytest.mark.asyncio
async def test_non_text_block_start_leaves_block_index_unchanged():
    session_reader.set_current_turn_id("s5", "turn-5")
    q = asyncio.Queue()
    await session_reader.dispatch_event("s5", _block_start_event(1, "text"), q, is_first_message=False)
    await session_reader.dispatch_event("s5", _text_delta_event("a", 1), q, is_first_message=False)
    # A tool_use (and thinking) block start must NOT move the tracked text
    # block index — only content_block_start with content_block.type=="text" does.
    await session_reader.dispatch_event("s5", _block_start_event(3, "tool_use"), q, is_first_message=False)
    await session_reader.dispatch_event("s5", _block_start_event(4, "thinking"), q, is_first_message=False)
    await session_reader.dispatch_event("s5", _text_delta_event("b", 4), q, is_first_message=False)
    chunks = [f for f in await _drain(q) if isinstance(f, AiChunk)]
    assert [c.block_index for c in chunks] == [1, 1]


@pytest.mark.asyncio
async def test_block_start_missing_raw_index_still_bumps_counter():
    # The raw CLI "index" field is no longer read at all — block_index comes
    # entirely from the per-session text-block counter — so a content_block_start
    # missing "index" must not crash and still assigns the next counter value.
    session_reader.set_current_turn_id("s6", "turn-6")
    q = asyncio.Queue()
    event = {"type": "stream_event",
             "event": {"type": "content_block_start",
                       "content_block": {"type": "text"}}}
    await session_reader.dispatch_event("s6", event, q, is_first_message=False)
    await session_reader.dispatch_event("s6", _text_delta_event("hi", 0), q, is_first_message=False)
    chunks = [f for f in await _drain(q) if isinstance(f, AiChunk)]
    assert chunks[0].block_index == 1


@pytest.mark.asyncio
async def test_restarted_raw_cli_index_does_not_collide_across_blocks():
    # The CLI restarts content-block indices per assistant message (a turn
    # that goes text -> tool call -> text again re-uses raw index 0 for BOTH
    # text blocks). Trusting the raw index would re-merge the two unrelated
    # text runs into one segment and hand the panel duplicate React keys —
    # the counter must keep them distinct even though the raw index repeats.
    session_reader.set_current_turn_id("s8", "turn-8")
    q = asyncio.Queue()
    await session_reader.dispatch_event("s8", _block_start_event(0), q, is_first_message=False)
    await session_reader.dispatch_event("s8", _text_delta_event("a", 0), q, is_first_message=False)
    # Simulates a new assistant message after a tool call: CLI resets to index 0.
    await session_reader.dispatch_event("s8", _block_start_event(0), q, is_first_message=False)
    await session_reader.dispatch_event("s8", _text_delta_event("b", 0), q, is_first_message=False)
    chunks = [f for f in await _drain(q) if isinstance(f, AiChunk)]
    assert [c.block_index for c in chunks] == [1, 2]


@pytest.mark.asyncio
async def test_empty_thinking_delta_emits_no_thinking_chunk():
    session_reader.set_current_turn_id("s7", "turn-7")
    q = asyncio.Queue()
    await session_reader.dispatch_event("s7", _thinking_delta_event(""), q, is_first_message=False)
    frames = await _drain(q)
    assert not any(isinstance(f, ThinkingChunk) for f in frames)
