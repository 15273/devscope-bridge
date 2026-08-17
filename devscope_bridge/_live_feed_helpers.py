"""
_live_feed_helpers.py — Helpers for the richer live-feed in session_reader.

Extracted from session_reader to keep that file within the 400-line limit.

Provides:
- _flatten_content: normalise tool_result content to a plain string
- _tool_result_summary: build a ≤80-char human summary for a tool result
- _emit_thinking_activity: emit AgentActivity when a thinking block is active
- _register_pending_tool_calls: record tool_use_id → name from assistant events
- _clear_pending_tool_calls: remove per-turn tracking on turn end
- _emit_tool_result_summaries: emit AgentActivity for non-sub-agent results
"""

import asyncio
import logging

from devscope_bridge import sub_agent_tracker
from devscope_bridge.models import AgentActivity
from devscope_bridge.tool_display import humanize_tool_name

logger = logging.getLogger(__name__)

# Per-session map: tool_use_id → { name, input }, for linking tool results.
# Shape: { session_name: { tool_use_id: { name, input } } }
_pending_tool_calls: dict[str, dict[str, dict]] = {}


def _flatten_content(content: object) -> str:
    """Flatten tool_result content (str or list of text blocks) to a plain string."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return " ".join(parts).strip()
    return str(content).strip() if content is not None else ""


def _tool_result_summary(tool_name: str, content: object, is_error: bool) -> str:
    """Build a ≤80-char summary for a tool result to show in the UI tool-log.

    Converts the tool_result content to a single human-readable line.
    Content may be a str, a list of {type, text} blocks, or anything else.
    """
    if is_error:
        raw = _flatten_content(content)
        if not raw:
            return "error"
        # Keep full bridge detail (503 session list, reload hint) in the tool row.
        if len(raw) <= 480:
            return "error: " + raw
        return "error: " + raw[:477] + "…"

    raw = _flatten_content(content)
    if not raw:
        return "ok"

    # Count output lines for Bash results; show first line + count
    lines = [ln for ln in raw.splitlines() if ln.strip()]
    if tool_name == "Bash" and len(lines) > 1:
        first = lines[0][:60]
        return f"{first!r} (+{len(lines) - 1} lines)" if len(first) < 60 else f"{len(lines)} lines"
    return raw[:80]


def register_pending_tool_calls(session: str, content: list) -> None:
    """Record tool_use_id → {name, input} from an assistant event's content list."""
    pending = _pending_tool_calls.setdefault(session, {})
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            tid = block.get("id")
            tname = block.get("name", "")
            if tid:
                pending[tid] = {
                    "name": tname,
                    "input": block.get("input") or {},
                }


def get_pending_tool_call(session: str, tool_use_id: str) -> dict | None:
    """Return {name, input} for a tool_use_id, or None."""
    return _pending_tool_calls.get(session, {}).get(tool_use_id)


def clear_pending_tool_calls(session: str) -> None:
    """Remove pending tool call tracking for a session (called on turn end)."""
    _pending_tool_calls.pop(session, None)


async def emit_tool_result_summaries(
    session: str, user_content: list, q: asyncio.Queue
) -> None:
    """Emit AgentActivity summary frames for non-sub-agent tool results.

    Skips sub-agent (Task/Agent) tool results — those are handled by
    sub_agent_tracker and identified via _pending_tool_calls rather than
    checking _in_flight, which may already have been cleared by the time
    this function runs.
    Emits one AgentActivity per result with a ≤80-char summary.
    """
    pending = _pending_tool_calls.get(session, {})
    # Lazy import: session_reader imports this module at load time, so a
    # module-level import here would be circular. Safe at call time since
    # session_reader is always fully loaded before any event is dispatched.
    from devscope_bridge.session_reader import get_current_turn_id
    turn_id = get_current_turn_id(session)

    for block in user_content:
        if not isinstance(block, dict) or block.get("type") != "tool_result":
            continue
        tool_use_id = block.get("tool_use_id", "")
        entry = pending.get(tool_use_id, {})
        tool_name = entry.get("name", "") if isinstance(entry, dict) else str(entry)
        if tool_name in sub_agent_tracker.SUB_AGENT_TOOL_NAMES:
            continue  # sub-agent results handled by sub_agent_tracker

        is_error = bool(block.get("is_error", False))
        summary = _tool_result_summary(tool_name, block.get("content"), is_error)
        label = _done_label(tool_name)

        await q.put(AgentActivity(
            session=session,
            label=label,
            tool=tool_name or None,
            detail=summary,
            call_id=tool_use_id or None,
            status="error" if is_error else "done",
            turn_id=turn_id,
        ))


def _done_label(tool_name: str) -> str:
    """Build the "done" label for a finished tool call.

    MCP tools get the same humanized "Server · Action" form used for the
    running-state label; other tools keep their existing "<tool> done" text.
    """
    if not tool_name:
        return "tool done"
    server_label, action_label = humanize_tool_name(tool_name)
    if server_label == tool_name:
        return f"{tool_name} done"
    label = f"{server_label} · {action_label}" if action_label else server_label
    return f"{label} — done"


async def emit_thinking_activity(
    session: str, event_inner: dict, q: asyncio.Queue
) -> None:
    """Emit AgentActivity(label="Thinking") when a thinking block is active.

    Handles two stream_event subtypes:
    - content_block_start with content_block.type == "thinking":  start label
    - content_block_delta with delta.type == "thinking_delta":  live preview

    Only the live label is surfaced; full thinking content is NOT buffered.
    Thinking blocks only appear when extended thinking is explicitly enabled.
    Since Claude v2.1.8 they are absent by default (GitHub issue #20127).
    """
    ev_type = event_inner.get("type", "")
    if ev_type == "content_block_start":
        block = event_inner.get("content_block", {})
        if block.get("type") == "thinking":
            await q.put(AgentActivity(session=session, label="Thinking", tool=None, detail=None))
    elif ev_type == "content_block_delta":
        delta = event_inner.get("delta", {})
        if delta.get("type") == "thinking_delta":
            snippet = str(delta.get("thinking", ""))[:60].strip()
            await q.put(AgentActivity(
                session=session, label="Thinking",
                tool=None, detail=snippet or None,
            ))
