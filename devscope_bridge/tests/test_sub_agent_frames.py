"""
test_sub_agent_frames.py

Tests for SubAgent lifecycle frame emission from dispatch_event.

Covers:
1. Single Task tool_use → SubAgent(phase='start') emitted
2. tool_result → SubAgent(phase='done', ok=True) emitted
3. tool_result is_error=True → SubAgent(phase='done', ok=False)
4. Ambient tool activity while Task open → phase='activity' emitted to in-flight agent
5. Task tool_use suppressed from generic AgentActivity (not double-emitted)
6. Turn end clears in-flight state (no leakage across turns)
7. Parallel sub-agents (two Task blocks) → two start frames, each completed independently
8. tool_result for unknown tool_use_id (not a Task) → no SubAgent emitted
9. subagent_type field used as name when present
10. description falls back to prompt when description absent
11. content as list of text blocks is flattened in result
"""

import asyncio
import pytest

from devscope_bridge import session_reader, sub_agent_tracker
from devscope_bridge.models import AgentActivity, AiDone, AiError, SubAgent


# ─────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clean_tracker():
    """Reset sub_agent_tracker state before and after each test."""
    sub_agent_tracker._in_flight.clear()
    yield
    sub_agent_tracker._in_flight.clear()


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _task_tool_use_block(
    tool_id: str = "toolu_001",
    description: str = "list files",
    prompt: str = "List the files in /tmp",
    subagent_type: str | None = None,
) -> dict:
    inp: dict = {"description": description, "prompt": prompt}
    if subagent_type is not None:
        inp["subagent_type"] = subagent_type
    return {"type": "tool_use", "id": tool_id, "name": "Task", "input": inp}


def _bash_tool_use_block(tool_id: str = "toolu_bash", command: str = "ls") -> dict:
    return {"type": "tool_use", "id": tool_id, "name": "Bash", "input": {"command": command}}


def _assistant_event(content: list) -> dict:
    return {"type": "assistant", "message": {"role": "assistant", "content": content}}


def _user_tool_result_event(
    tool_use_id: str,
    result_text: str = "done",
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
                    "content": result_text,
                }
            ],
        },
    }


def _result_event(is_error: bool = False) -> dict:
    return {
        "type": "result",
        "subtype": "success",
        "is_error": is_error,
        "result": "ok",
        "permission_denials": [],
        "usage": {},
        "total_cost_usd": 0,
        "duration_ms": 0,
    }


async def _drain(q: asyncio.Queue) -> list:
    """Non-blocking drain of everything currently in the queue."""
    frames = []
    while True:
        try:
            frames.append(q.get_nowait())
        except asyncio.QueueEmpty:
            break
    return frames


# ─────────────────────────────────────────────
# Test 1: Single Task spawn → SubAgent(phase='start')
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_task_tool_use_emits_sub_agent_start():
    """A Task tool_use in an assistant event emits SubAgent(phase='start')."""
    q: asyncio.Queue = asyncio.Queue()
    block = _task_tool_use_block(tool_id="toolu_001", description="run tests")
    await session_reader.dispatch_event(
        "sess", _assistant_event([block]), q, is_first_message=False
    )
    frames = await _drain(q)

    sub_starts = [f for f in frames if isinstance(f, SubAgent) and f.phase == "start"]
    assert len(sub_starts) == 1
    sa = sub_starts[0]
    assert sa.session == "sess"
    assert sa.agent_id == "toolu_001"
    assert sa.name == "sub-agent"  # no subagent_type provided
    assert "run tests" in sa.description


# ─────────────────────────────────────────────
# Test 2: tool_result → SubAgent(phase='done', ok=True)
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tool_result_emits_sub_agent_done_ok():
    """A tool_result matching an in-flight Task emits SubAgent(phase='done', ok=True)."""
    q: asyncio.Queue = asyncio.Queue()
    block = _task_tool_use_block(tool_id="toolu_002")

    # Spawn
    await session_reader.dispatch_event(
        "sess2", _assistant_event([block]), q, is_first_message=False
    )
    await _drain(q)

    # Complete
    await session_reader.dispatch_event(
        "sess2",
        _user_tool_result_event("toolu_002", result_text="['a.txt', 'b.txt']"),
        q,
        is_first_message=False,
    )
    frames = await _drain(q)

    done_frames = [f for f in frames if isinstance(f, SubAgent) and f.phase == "done"]
    assert len(done_frames) == 1
    sa = done_frames[0]
    assert sa.session == "sess2"
    assert sa.agent_id == "toolu_002"
    assert sa.ok is True
    assert "a.txt" in (sa.result or "")


# ─────────────────────────────────────────────
# Test 3: is_error tool_result → done with ok=False
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tool_result_is_error_emits_done_not_ok():
    """tool_result with is_error=True → SubAgent(phase='done', ok=False)."""
    q: asyncio.Queue = asyncio.Queue()
    await session_reader.dispatch_event(
        "sess3",
        _assistant_event([_task_tool_use_block(tool_id="toolu_003")]),
        q,
        is_first_message=False,
    )
    await _drain(q)

    await session_reader.dispatch_event(
        "sess3",
        _user_tool_result_event("toolu_003", result_text="timeout exceeded", is_error=True),
        q,
        is_first_message=False,
    )
    frames = await _drain(q)

    done_frames = [f for f in frames if isinstance(f, SubAgent) and f.phase == "done"]
    assert len(done_frames) == 1
    assert done_frames[0].ok is False


# ─────────────────────────────────────────────
# Test 4: Ambient tool activity while Task open → phase='activity'
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tool_activity_while_task_open_emits_activity_frame():
    """A Bash tool while a Task is open also emits SubAgent(phase='activity')."""
    q: asyncio.Queue = asyncio.Queue()

    # Spawn sub-agent
    await session_reader.dispatch_event(
        "sess4",
        _assistant_event([_task_tool_use_block(tool_id="toolu_004")]),
        q,
        is_first_message=False,
    )
    await _drain(q)

    # Another assistant event with a Bash tool (while sub-agent is still open)
    await session_reader.dispatch_event(
        "sess4",
        _assistant_event([_bash_tool_use_block()]),
        q,
        is_first_message=False,
    )
    frames = await _drain(q)

    activity_frames = [f for f in frames if isinstance(f, SubAgent) and f.phase == "activity"]
    assert len(activity_frames) == 1
    af = activity_frames[0]
    assert af.agent_id == "toolu_004"
    assert af.activity is not None
    assert "Running command" in af.activity or "command" in af.activity.lower()


# ─────────────────────────────────────────────
# Test 5: Task tool_use does NOT emit generic AgentActivity
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_task_tool_use_not_emitted_as_generic_agent_activity():
    """Task tool_use must NOT produce a generic AgentActivity frame (only SubAgent frames)."""
    q: asyncio.Queue = asyncio.Queue()
    await session_reader.dispatch_event(
        "sess5",
        _assistant_event([_task_tool_use_block(tool_id="toolu_005")]),
        q,
        is_first_message=False,
    )
    frames = await _drain(q)

    activity_frames = [f for f in frames if isinstance(f, AgentActivity)]
    assert len(activity_frames) == 0, (
        f"Task tool_use should not emit AgentActivity, got: {activity_frames}"
    )
    sub_starts = [f for f in frames if isinstance(f, SubAgent)]
    assert len(sub_starts) == 1


# ─────────────────────────────────────────────
# Test 6: Turn end clears in-flight state
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_turn_end_clears_in_flight_state():
    """After a result event, in-flight sub-agent state is cleared for the session."""
    q: asyncio.Queue = asyncio.Queue()

    await session_reader.dispatch_event(
        "sess6",
        _assistant_event([_task_tool_use_block(tool_id="toolu_006")]),
        q,
        is_first_message=False,
    )

    # Verify it's tracked
    assert sub_agent_tracker.has_in_flight("sess6")

    # Turn ends without tool_result (abnormal — e.g. error turn)
    await session_reader.dispatch_event(
        "sess6", _result_event(), q, is_first_message=False
    )

    # State must be cleared
    assert not sub_agent_tracker.has_in_flight("sess6")


# ─────────────────────────────────────────────
# Test 7: Parallel sub-agents
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_parallel_sub_agents_tracked_independently():
    """Two Task tool_use blocks → two start frames; each completed by its own tool_result."""
    q: asyncio.Queue = asyncio.Queue()

    block_a = _task_tool_use_block(tool_id="toolu_A", description="task A")
    block_b = _task_tool_use_block(tool_id="toolu_B", description="task B")

    # Both spawned in the same assistant event
    await session_reader.dispatch_event(
        "sess7", _assistant_event([block_a, block_b]), q, is_first_message=False
    )
    frames_after_spawn = await _drain(q)

    starts = [f for f in frames_after_spawn if isinstance(f, SubAgent) and f.phase == "start"]
    assert len(starts) == 2, f"Expected 2 start frames, got {len(starts)}"
    agent_ids = {s.agent_id for s in starts}
    assert agent_ids == {"toolu_A", "toolu_B"}

    # Complete agent B first (non-sequential is fine)
    await session_reader.dispatch_event(
        "sess7",
        _user_tool_result_event("toolu_B", result_text="B result"),
        q,
        is_first_message=False,
    )
    frames_b = await _drain(q)
    done_b = [f for f in frames_b if isinstance(f, SubAgent) and f.phase == "done"]
    assert len(done_b) == 1
    assert done_b[0].agent_id == "toolu_B"
    assert done_b[0].ok is True

    # A still in flight
    assert sub_agent_tracker.has_in_flight("sess7")

    # Complete agent A
    await session_reader.dispatch_event(
        "sess7",
        _user_tool_result_event("toolu_A", result_text="A result"),
        q,
        is_first_message=False,
    )
    frames_a = await _drain(q)
    done_a = [f for f in frames_a if isinstance(f, SubAgent) and f.phase == "done"]
    assert len(done_a) == 1
    assert done_a[0].agent_id == "toolu_A"

    # Both done — no more in-flight
    assert not sub_agent_tracker.has_in_flight("sess7")


# ─────────────────────────────────────────────
# Test 8: tool_result for non-Task tool_use_id → no SubAgent emitted
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_unknown_tool_result_does_not_emit_sub_agent():
    """tool_result for an id that was not a Task spawn → no SubAgent frame."""
    q: asyncio.Queue = asyncio.Queue()

    # No Task spawned; simulate a Bash tool_result arriving
    await session_reader.dispatch_event(
        "sess8",
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_unrelated",
                        "is_error": False,
                        "content": "some bash output",
                    }
                ],
            },
        },
        q,
        is_first_message=False,
    )
    frames = await _drain(q)

    sub_frames = [f for f in frames if isinstance(f, SubAgent)]
    assert len(sub_frames) == 0, f"No SubAgent expected for non-Task result: {sub_frames}"


# ─────────────────────────────────────────────
# Test 9: subagent_type used as name when present
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_subagent_type_used_as_name():
    """SubAgent.name comes from input.subagent_type when present."""
    q: asyncio.Queue = asyncio.Queue()
    block = _task_tool_use_block(tool_id="toolu_009", subagent_type="test-runner")
    await session_reader.dispatch_event(
        "sess9", _assistant_event([block]), q, is_first_message=False
    )
    frames = await _drain(q)

    starts = [f for f in frames if isinstance(f, SubAgent) and f.phase == "start"]
    assert len(starts) == 1
    assert starts[0].name == "test-runner"


# ─────────────────────────────────────────────
# Test 10: description falls back to prompt
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_description_falls_back_to_prompt():
    """When input.description is absent, input.prompt is used as description."""
    q: asyncio.Queue = asyncio.Queue()
    block = {
        "type": "tool_use",
        "id": "toolu_010",
        "name": "Task",
        "input": {"prompt": "run all tests and report results"},
    }
    await session_reader.dispatch_event(
        "sess10", _assistant_event([block]), q, is_first_message=False
    )
    frames = await _drain(q)

    starts = [f for f in frames if isinstance(f, SubAgent) and f.phase == "start"]
    assert len(starts) == 1
    assert "run all tests" in starts[0].description


# ─────────────────────────────────────────────
# Test 11: content as list of text blocks is flattened in result
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_result_content_list_is_flattened():
    """tool_result content as list[{type,text}] is joined into a single string."""
    q: asyncio.Queue = asyncio.Queue()
    await session_reader.dispatch_event(
        "sess11",
        _assistant_event([_task_tool_use_block(tool_id="toolu_011")]),
        q,
        is_first_message=False,
    )
    await _drain(q)

    user_event = {
        "type": "user",
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "toolu_011",
                    "is_error": False,
                    "content": [
                        {"type": "text", "text": "part one"},
                        {"type": "text", "text": " part two"},
                    ],
                }
            ],
        },
    }
    await session_reader.dispatch_event("sess11", user_event, q, is_first_message=False)
    frames = await _drain(q)

    done_frames = [f for f in frames if isinstance(f, SubAgent) and f.phase == "done"]
    assert len(done_frames) == 1
    assert "part one" in (done_frames[0].result or "")
    assert "part two" in (done_frames[0].result or "")


# ─────────────────────────────────────────────
# Test 12: No activity frame when no sub-agent is in flight
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_no_activity_frame_when_no_task_open():
    """Bash tool while no Task is open → AgentActivity but NO SubAgent(phase='activity')."""
    q: asyncio.Queue = asyncio.Queue()
    await session_reader.dispatch_event(
        "sess12",
        _assistant_event([_bash_tool_use_block()]),
        q,
        is_first_message=False,
    )
    frames = await _drain(q)

    sub_activity = [f for f in frames if isinstance(f, SubAgent) and f.phase == "activity"]
    assert len(sub_activity) == 0, f"Expected no SubAgent activity: {sub_activity}"

    # Generic AgentActivity still emitted
    agent_activity = [f for f in frames if isinstance(f, AgentActivity)]
    assert len(agent_activity) == 1


# ─────────────────────────────────────────────
# Test 13: Full lifecycle produces correct phase sequence
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_full_lifecycle_phase_order():
    """start → (optional activity) → done, then AiDone — verify ordering."""
    q: asyncio.Queue = asyncio.Queue()

    # 1. Spawn
    await session_reader.dispatch_event(
        "sess13",
        _assistant_event([_task_tool_use_block(tool_id="toolu_013", description="full test")]),
        q,
        is_first_message=False,
    )
    # 2. Activity (Bash fires while sub-agent open)
    await session_reader.dispatch_event(
        "sess13",
        _assistant_event([_bash_tool_use_block()]),
        q,
        is_first_message=False,
    )
    # 3. Complete
    await session_reader.dispatch_event(
        "sess13",
        _user_tool_result_event("toolu_013", result_text="success"),
        q,
        is_first_message=False,
    )
    # 4. Turn done
    await session_reader.dispatch_event(
        "sess13", _result_event(), q, is_first_message=False
    )

    frames = await _drain(q)
    sub_frames = [f for f in frames if isinstance(f, SubAgent)]
    phases = [f.phase for f in sub_frames]

    assert "start" in phases
    assert "done" in phases
    start_idx = next(i for i, f in enumerate(sub_frames) if f.phase == "start")
    done_idx = next(i for i, f in enumerate(sub_frames) if f.phase == "done")
    assert start_idx < done_idx, "start must precede done"

    # AiDone comes after all SubAgent frames
    all_frames = frames
    done_ai_idx = next((i for i, f in enumerate(all_frames) if isinstance(f, AiDone)), None)
    last_sub_idx = max(i for i, f in enumerate(all_frames) if isinstance(f, SubAgent))
    assert done_ai_idx is not None
    assert last_sub_idx < done_ai_idx, "All SubAgent frames must precede AiDone"
