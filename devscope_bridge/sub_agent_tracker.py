"""
sub_agent_tracker.py — Per-session state and helpers for Task tool sub-agents.

Tracks in-flight sub-agents (spawned by the parent via the Task tool) and emits
SubAgent lifecycle frames onto the session's output queue.

Stream-json visibility constraints
-----------------------------------
In the CLI ``--output-format stream-json`` path the sub-agent's internal events
are NOT forwarded to the parent stdout.  Only two signals are visible:

  1. Sub-agent SPAWN: an ``assistant`` event whose content list contains a
     ``tool_use`` block with ``name == "Task"``.  The block has ``id`` (the
     stable agent_id for the lifecycle), ``input.description``,
     ``input.prompt``, and optionally ``input.subagent_type``.

  2. Sub-agent COMPLETION: a ``user`` event whose content list contains a
     ``tool_result`` block with ``tool_use_id`` matching the Task's ``id``.
     ``is_error`` signals failure; ``content`` holds the sub-agent's output.

``parent_tool_use_id`` (which would link the sub-agent's own tool calls back
to the parent Task) is only available via the Agent SDK, NOT the CLI path.
Full per-step child activity therefore cannot be linked; phase="activity"
frames are synthesised from ambient top-level activity while a Task is open.
"""

import asyncio
import logging
from typing import TYPE_CHECKING

from devscope_bridge.models import SubAgent

if TYPE_CHECKING:
    pass  # keep imports light; queue type is asyncio.Queue

logger = logging.getLogger(__name__)

# Maps session_name → {agent_id: SubAgent(phase="start", ...)}
# Populated on Task tool_use in assistant event; removed on matching tool_result.
_in_flight: dict[str, dict[str, SubAgent]] = {}


def clear_session(session: str) -> None:
    """Remove all in-flight tracking for a session (called on turn end or cleanup)."""
    _in_flight.pop(session, None)


def has_in_flight(session: str) -> bool:
    """Return True if there are any Task sub-agents still running for this session."""
    return bool(_in_flight.get(session))


# The CLI renamed the sub-agent tool "Task" → "Agent" (~2.1.22x); accept both.
SUB_AGENT_TOOL_NAMES = ("Task", "Agent")


def extract_task_blocks(content: list) -> list[dict]:
    """Return all sub-agent (Task/Agent) tool_use blocks from an assistant message."""
    return [
        block for block in content
        if isinstance(block, dict)
        and block.get("type") == "tool_use"
        and block.get("name") in SUB_AGENT_TOOL_NAMES
    ]


async def emit_sub_agent_starts(
    session: str, blocks: list[dict], q: asyncio.Queue
) -> None:
    """Emit SubAgent(phase='start') for each Task tool_use block and track them."""
    agents = _in_flight.setdefault(session, {})
    for block in blocks:
        agent_id = block.get("id", "")
        inp = block.get("input") or {}
        name = str(inp.get("subagent_type") or "sub-agent")
        raw_desc = str(inp.get("description") or inp.get("prompt") or "")
        description = raw_desc[:200] or "(no description)"
        frame = SubAgent(
            session=session,
            agent_id=agent_id,
            name=name,
            description=description,
            phase="start",
        )
        agents[agent_id] = frame
        await q.put(frame)
        logger.info(
            "Session '%s' sub-agent start: agent_id=%s name=%s",
            session, agent_id, name,
        )


async def emit_activity_to_in_flight(
    session: str, label: str, q: asyncio.Queue
) -> None:
    """Propagate a tool activity label to the most-recently-spawned in-flight sub-agent.

    This is an approximation: in the CLI stream-json path we cannot link a
    top-level tool_use to a specific sub-agent because parent_tool_use_id is
    not forwarded.  We attribute ambient activity to the last-inserted agent.
    """
    agents = _in_flight.get(session, {})
    if not agents:
        return
    latest_agent_id = next(reversed(agents))
    start_frame = agents[latest_agent_id]
    await q.put(SubAgent(
        session=session,
        agent_id=latest_agent_id,
        name=start_frame.name,
        description=start_frame.description,
        phase="activity",
        activity=label,
    ))


async def handle_tool_results(
    session: str, content: list, q: asyncio.Queue
) -> None:
    """Emit SubAgent(phase='done') for tool_result blocks matching in-flight Tasks."""
    agents = _in_flight.get(session, {})
    if not agents:
        return
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "tool_result":
            continue
        tool_use_id = block.get("tool_use_id", "")
        if tool_use_id not in agents:
            continue
        start_frame = agents.pop(tool_use_id)
        is_error = bool(block.get("is_error", False))
        raw_result = block.get("content") or ""
        if isinstance(raw_result, list):
            raw_result = " ".join(
                b.get("text", "") for b in raw_result if isinstance(b, dict)
            )
        result_preview = str(raw_result)[:200]
        await q.put(SubAgent(
            session=session,
            agent_id=tool_use_id,
            name=start_frame.name,
            description=start_frame.description,
            phase="done",
            ok=not is_error,
            result=result_preview or None,
        ))
        logger.info(
            "Session '%s' sub-agent done: agent_id=%s ok=%s",
            session, tool_use_id, not is_error,
        )
