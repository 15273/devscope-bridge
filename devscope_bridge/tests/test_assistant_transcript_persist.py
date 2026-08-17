"""
test_assistant_transcript_persist.py — A9/RC-5 fallback hole: the Claude path
never wrote assistant turns to the bridge-owned transcript, so a read after
session_id loss returned questions with no answers.

Coverage
--------
1. dispatch_event accumulates stream_event text_delta chunks and, on `result`,
   appends the full assistant reply to the bridge transcript.
2. Empty/whitespace-only assistant text is not persisted (nothing to save).
3. A turn that ends abnormally (reader exits without a `result` event) drops
   its partial accumulation instead of leaking into the next turn.
4. End-to-end: turn completes -> bridge JSONL has a user+assistant pair even
   when session_id is cleared (the plan's exact Test line for A9).
"""

import json
import pytest

import devscope_bridge.session_reader as sr
import devscope_bridge.session_store as store


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "BRIDGE_DIR", tmp_path)
    monkeypatch.setattr(store, "BRIDGE_TRANSCRIPTS_DIR", tmp_path / "chat-transcripts")
    store._TRANSCRIPT_CACHE.clear()
    sr._assistant_text_accum.clear()
    yield
    sr._assistant_text_accum.clear()


def _chunk_event(text: str) -> dict:
    return {
        "type": "stream_event",
        "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": text}},
    }


def _result_event(text: str = "ok") -> dict:
    return {
        "type": "result", "subtype": "success", "is_error": False,
        "result": text, "usage": {}, "total_cost_usd": 0, "duration_ms": 0,
    }


@pytest.mark.asyncio
async def test_result_persists_accumulated_assistant_text():
    import asyncio
    q: asyncio.Queue = asyncio.Queue()

    await sr.dispatch_event("persist-sess", _chunk_event("Hello "), q, is_first_message=False)
    await sr.dispatch_event("persist-sess", _chunk_event("world"), q, is_first_message=False)
    done = await sr.dispatch_event("persist-sess", _result_event(), q, is_first_message=False)

    assert done is True
    turns = store.read_transcript_turns("persist-sess")
    assistant_turns = [t for t in turns if t["role"] == "assistant"]
    assert len(assistant_turns) == 1
    assert assistant_turns[0]["text"] == "Hello world"
    # Accumulator must be cleared after flushing.
    assert "persist-sess" not in sr._assistant_text_accum


@pytest.mark.asyncio
async def test_empty_assistant_text_is_not_persisted():
    import asyncio
    q: asyncio.Queue = asyncio.Queue()

    await sr.dispatch_event("empty-sess", _result_event(), q, is_first_message=False)

    turns = store.read_transcript_turns("empty-sess")
    assert turns == []


@pytest.mark.asyncio
async def test_abnormal_turn_end_drops_partial_text_not_next_turn():
    """continuous_reader's finally clears any partial accumulation so it
    cannot bleed into the NEXT turn's assistant text."""
    sr._accumulate_assistant_text("leaky-sess", "half a reply")
    sr._consume_assistant_text("leaky-sess")  # what the finally block calls
    assert "leaky-sess" not in sr._assistant_text_accum

    # A later, real turn's text must not be contaminated by the dropped partial.
    import asyncio
    q: asyncio.Queue = asyncio.Queue()
    await sr.dispatch_event("leaky-sess", _chunk_event("fresh answer"), q, is_first_message=False)
    await sr.dispatch_event("leaky-sess", _result_event(), q, is_first_message=False)

    turns = store.read_transcript_turns("leaky-sess")
    assistant_turns = [t for t in turns if t["role"] == "assistant"]
    assert len(assistant_turns) == 1
    assert assistant_turns[0]["text"] == "fresh answer"


@pytest.mark.asyncio
async def test_end_to_end_transcript_has_user_and_assistant_after_session_id_cleared():
    """Turn completes -> bridge JSONL has user+assistant pair when session_id
    cleared (A9's exact plan Test line)."""
    import asyncio
    q: asyncio.Queue = asyncio.Queue()

    store.append_bridge_turn("e2e-sess", "user", "what is the plan?")
    await sr.dispatch_event("e2e-sess", _chunk_event("The plan is "), q, is_first_message=False)
    await sr.dispatch_event("e2e-sess", _chunk_event("to ship it."), q, is_first_message=False)
    await sr.dispatch_event("e2e-sess", _result_event(), q, is_first_message=False)

    # Simulate the session_id-loss recovery path — the CLI JSONL is gone/stale,
    # so read_transcript_turns falls back to the bridge-owned transcript.
    store.clear_session_id("e2e-sess")

    turns = store.read_transcript_turns("e2e-sess")
    roles = [t["role"] for t in turns]
    assert "user" in roles and "assistant" in roles
    assistant_text = next(t["text"] for t in turns if t["role"] == "assistant")
    assert assistant_text == "The plan is to ship it."
