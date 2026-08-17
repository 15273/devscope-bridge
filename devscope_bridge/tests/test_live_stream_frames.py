"""New live-stream frames: ThinkingChunk, TurnResult, and turn identity fields."""
from devscope_bridge.models import (
    AgentActivity, AiChunk, AiDone, ThinkingChunk, TurnResult, TurnState,
)


def test_ai_chunk_defaults_are_backward_compatible():
    c = AiChunk(session="s", text="hi")
    d = c.model_dump()
    assert d["turn_id"] is None and d["block_index"] == 0


def test_ai_chunk_carries_turn_identity():
    c = AiChunk(session="s", text="hi", turn_id="t1", block_index=2)
    assert c.model_dump()["turn_id"] == "t1"
    assert c.model_dump()["block_index"] == 2


def test_thinking_chunk_shape():
    t = ThinkingChunk(session="s", text="hmm", turn_id="t1")
    assert t.model_dump()["type"] == "thinking_chunk"


def test_turn_result_shape():
    r = TurnResult(session="s", turn_id="t1", duration_ms=1200, cost_usd=0.01,
                   input_tokens=10, output_tokens=20, model="claude-sonnet-5")
    d = r.model_dump()
    assert d["type"] == "turn_result" and d["output_tokens"] == 20


def test_lifecycle_frames_accept_turn_id():
    assert AiDone(session="s", turn_id="t1").turn_id == "t1"
    assert TurnState(session="s", running=True, turn_id="t1").turn_id == "t1"
    assert AgentActivity(session="s", label="x", turn_id="t1").turn_id == "t1"
