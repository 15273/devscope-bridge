"""
session_reader.py — Continuous stdout reader for persistent Claude processes.

Parses stream-json events from a long-running claude process, emitting
AiChunk/AiDone/AiError/SessionReady/RateLimit/PermissionRequest onto the
session's out_queue.
End-of-turn is detected via the {"type":"result"} event (NOT process exit).

Turn watchdog
-------------
If a turn produces NO stdout events for _WATCHDOG_HEARTBEAT_S seconds, a
lightweight AgentActivity("still working…") frame is emitted so the UI shows
life.  After _WATCHDOG_HARD_CAP_S of total silence, an AiError is emitted and
the optional hard_interrupt_fn is called so the session manager can
SIGINT + respawn the process, guaranteeing the UI always unblocks.

Two independent flags track the two thresholds so the hard cap always fires
even after the heartbeat has already been emitted.

Permission handling
-------------------
Plan mode: claude emits an assistant event with an ExitPlanMode tool_use block
when it has a plan ready.  The runtime immediately returns is_error:true from
that tool call and the turn ends normally (result/success).  We detect the
ExitPlanMode tool_use in the assistant event and emit a PermissionRequest
(kind="plan") at that point so the UI can surface the plan immediately.
The PermissionRequest is emitted BEFORE the result event so the UI is never
left silently waiting — we still emit AiDone after the result event.

Default mode: tool calls blocked by the sandbox produce is_error:true
tool_result events inline.  The result event may carry a permission_denials
array.  We emit a PermissionRequest(kind="permission_denied") for each entry
so the UI can show what was blocked, even though no approval is possible.

Thinking blocks
---------------
When extended thinking is enabled, claude emits stream_event wrappers around
content_block_start (type="thinking") and content_block_delta
(type="thinking_delta").  We emit AgentActivity(label="Thinking") so the UI
can show "Thinking…" in the activity strip.  Thinking is ephemeral — only the
live label is surfaced; full thinking content is NOT buffered or forwarded.

Tool result summaries
---------------------
When a user event carries tool_result blocks for non-sub-agent tools, we emit
AgentActivity(label="<tool> done", detail=<short summary>) so the UI tool-log
can show e.g. "Bash · 3 lines" instead of just "ok".  We track pending tool
calls (tool_use_id → name) from assistant events to link results back.
"""

import asyncio
import json
import logging
import time
import uuid
from collections import deque
from collections.abc import Callable

from devscope_bridge import session_store
from devscope_bridge import sub_agent_tracker
from devscope_bridge import _live_feed_helpers as _lfh
from devscope_bridge.models import (
    AgentActivity, AiChunk, AiDone, AiError, PermissionOption,
    PermissionRequest, RateLimit, SessionReady, ThinkingChunk, TodoUpdate,
    TurnResult, TurnState, Usage,
)
from devscope_bridge.tool_display import extract_param_preview, humanize_tool_name

logger = logging.getLogger(__name__)

_WATCHDOG_HEARTBEAT_S = 120   # emit a periodic heartbeat every this many seconds of turn time
_WATCHDOG_MEDIC_S = 300       # spawn the Watchdog Medic after this many seconds of silence
# Browser / MCP tools can run with zero stdout for several minutes (official SDK:
# silent during tool execution). 5 min was too aggressive for Chrome DevTools.
_WATCHDOG_HARD_CAP_S = 900    # interrupt after this many seconds of silence (15 min)
# Wall-clock turn caps — fire even when periodic stream_event stdout resets silence
# (long sub-agent runs can trickle output forever and never hit silence thresholds).
_WATCHDOG_TURN_WALL_MEDIC_S = 900   # 15 min total turn → medic
_WATCHDOG_TURN_WALL_CAP_S = 2400    # 40 min total turn → hard interrupt
# Absolute ceiling — never defer past this, even for long_running / medic_active.
# Prevents overnight ghost turns when trickle stdout or a wedged medic skips caps.
_WATCHDOG_TURN_ABSOLUTE_CAP_S = 7200  # 2 h
# After hard_due, medic may defer SIGINT this long — then hard-cap fires anyway.
_WATCHDOG_MEDIC_DEFER_MAX_S = 180
# Soft, non-destructive notice that a turn has been running a long time — just
# a hint; Stop/medic remain available. Well below the wall/absolute hard caps.
_WATCHDOG_SOFT_WALL_S = 600   # 10 min
# A6/A8: how long a steering message (written to stdin mid-turn) may sit
# without the CLI starting a new turn before we warn it may have been dropped.
_STEERING_STALL_S = 120

# Sessions exempt from silence-based hard-cap (long-running orchestrator workers).
# Heartbeat + medic still fire; wall/absolute caps still apply.
_long_running: set[str] = set()


def mark_long_running(name: str) -> None:
    _long_running.add(name)


def clear_long_running(name: str) -> None:
    _long_running.discard(name)


def is_long_running(name: str) -> bool:
    return name in _long_running


# Maps pending PermissionRequest request_id → a superset dict carrying both the
# fields session_manager.send_approval needs to resolve it (session, kind,
# tool_name, tool_input, questions) AND the presentation fields needed to
# reconstruct the original PermissionRequest frame for GET /pending (contract
# 3 / A2): title, description, options, plan_file_path, created_at. Populated
# by the _emit_*_request helpers below; consumed by send_approval (pop) and by
# get_pending_permissions (read-only, for reconnect/reopen recovery).
_pending_permissions: dict[str, dict] = {}

# Per-session ring buffer of recent event summaries — the Watchdog Medic reads
# this to see what the stuck turn was doing right before it went silent.
_RECENT_EVENTS_MAX = 25
_recent_events: dict[str, deque] = {}

# ─────────────────────────────────────────────
# Liveness state (contract 2 / A3) — populated as stdout events are consumed,
# read on-demand by session_manager.get_session_state() for GET /sessions.
# ─────────────────────────────────────────────

_last_output_at: dict[str, float] = {}   # session -> epoch seconds of last stdout
_current_tool: dict[str, str | None] = {}  # session -> label of the tool in flight
# Per-turn accumulator of the assistant's streamed text, flushed to the bridge
# transcript on `result` (A9) — the Claude path never persisted assistant turns,
# so a transcript read after session_id loss returned questions with no answers.
_assistant_text_accum: dict[str, list[str]] = {}

# Per-session registry of the currently-minted turn id (set by
# session_manager.run_prompt right before a user turn is dispatched). Not
# cleared at turn end — keeping the last id lets late frames still tag
# correctly. Consumed by later stream-tagging work (Task 3).
_current_turn_ids: dict[str, str] = {}


def set_current_turn_id(name: str, turn_id: str | None) -> None:
    if turn_id is None:
        _current_turn_ids.pop(name, None)
    else:
        _current_turn_ids[name] = turn_id


def get_current_turn_id(name: str) -> str | None:
    return _current_turn_ids.get(name)


# Per-session index of the current text content block (set on
# content_block_start, read when tagging AiChunk so the panel can group
# streamed text by block instead of assuming a single running block).
#
# NOT the raw CLI content_block_start index: the CLI restarts block indices
# from 0 on every assistant message within a turn (e.g. text -> tool call ->
# text again re-uses index 0), so the raw index is not unique across a turn
# and would both re-merge unrelated text runs and hand the panel duplicate
# React keys. `_text_block_counters` is a per-session counter bumped on every
# text content_block_start instead, giving a turn-unique, monotonically
# increasing block_index. Reset at `result` (end of turn).
_current_block_index: dict[str, int] = {}
_text_block_counters: dict[str, int] = {}


# Per-session bounded stderr tail. asyncio.StreamReader supports only ONE
# consumer, and session_manager._drain_stderr is that sole consumer of
# proc.stderr (it must be, to keep a chatty child from blocking on a full
# pipe). continuous_reader's process-exit path used to `await proc.stderr
# .read()` directly for crash diagnostics, but that raced with the drain
# loop — deterministically returning b"" after the drain had already
# consumed everything, or raising RuntimeError("already waiting for
# incoming data") if both awaited concurrently. It now reads this buffer,
# fed line-by-line by _drain_stderr, instead.
_STDERR_TAIL_MAX_CHARS = 500
_stderr_tails: dict[str, deque] = {}


def append_stderr_line(name: str, line: str) -> None:
    """Feed one decoded stderr line into the session's bounded tail buffer.

    Called only by session_manager._drain_stderr, the sole reader of
    proc.stderr.
    """
    _stderr_tails.setdefault(name, deque(maxlen=50)).append(line)


def get_stderr_tail(name: str) -> str:
    """Return the last ~500 chars of stderr collected for this session."""
    buf = _stderr_tails.get(name)
    if not buf:
        return ""
    return "\n".join(buf)[-_STDERR_TAIL_MAX_CHARS:]


def touch_output(name: str) -> None:
    """Record that session `name` just produced real stdout (contract-2 last_output_at)."""
    _last_output_at[name] = time.time()


def get_last_output_at(name: str) -> float | None:
    return _last_output_at.get(name)


def set_current_tool(name: str, tool: str | None) -> None:
    """Track the tool currently in flight for this session (None = idle)."""
    if tool is None:
        _current_tool.pop(name, None)
    else:
        _current_tool[name] = tool


def get_current_tool(name: str) -> str | None:
    return _current_tool.get(name)


def get_awaiting_kind(name: str) -> str | None:
    """The kind of the pending interactive request blocking this session, if any."""
    for meta in _pending_permissions.values():
        if meta.get("session") == name:
            return meta.get("kind")
    return None


def get_pending_permissions(name: str) -> list[dict]:
    """Unresolved interactive requests for a session, as PermissionRequest frame JSON.

    Backs GET /sessions/{name}/pending (contract 3 / A2) — lets a panel that
    was closed or disconnected when a card arrived recover it on reopen.
    """
    out: list[dict] = []
    for request_id, meta in _pending_permissions.items():
        if meta.get("session") != name:
            continue
        out.append({
            "type": "permission_request",
            "session": name,
            "request_id": request_id,
            "kind": meta.get("kind"),
            "title": meta.get("title", ""),
            "description": meta.get("description", ""),
            "options": meta.get("options", []),
            "plan_file_path": meta.get("plan_file_path"),
            "questions": meta.get("questions"),
            "tool_name": meta.get("tool_name"),
            "tool_input": meta.get("tool_input"),
            "created_at": meta.get("created_at"),
        })
    return out


def _accumulate_assistant_text(name: str, text: str) -> None:
    _assistant_text_accum.setdefault(name, []).append(text)


def _consume_assistant_text(name: str) -> str:
    """Pop and join this session's accumulated assistant text for the turn."""
    return "".join(_assistant_text_accum.pop(name, []))

# Per-session cumulative usage.  Keyed by session name; each value is a dict
# with "input_tokens", "output_tokens", "cache_read_tokens",
# "cache_write_tokens", "cost_usd", "turn_count" accumulated across all turns.
# Populated by accumulate_usage(); read by /usage command handler.
_session_usage: dict[str, dict] = {}


def accumulate_usage(session_name: str, event: dict) -> None:
    """Update the per-session cumulative usage from a result event.

    Called from dispatch_event whenever a result event arrives. Reads both
    the aggregated top-level usage dict and total_cost_usd from the event.
    """
    usage = event.get("usage") or {}
    acc = _session_usage.setdefault(session_name, {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "cost_usd": 0.0,
        "turn_count": 0,
    })
    acc["input_tokens"] += int(usage.get("input_tokens") or 0)
    acc["output_tokens"] += int(usage.get("output_tokens") or 0)
    acc["cache_read_tokens"] += int(usage.get("cache_read_input_tokens") or 0)
    acc["cache_write_tokens"] += int(usage.get("cache_creation_input_tokens") or 0)
    acc["cost_usd"] += float(event.get("total_cost_usd") or 0)
    acc["turn_count"] += 1
    from devscope_bridge import task_usage
    task_usage.record_turn_usage(session_name, event)


def get_session_usage(session_name: str) -> dict:
    """Return accumulated usage for a session (copy; defaults to zeros)."""
    default: dict = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "cost_usd": 0.0,
        "turn_count": 0,
    }
    return dict(_session_usage.get(session_name, default))


def reset_session_usage(session_name: str) -> None:
    """Clear accumulated usage for a session (call on /new or /compact)."""
    _session_usage.pop(session_name, None)


def record_recent_event(name: str, event: dict) -> None:
    """Append a compact summary of one stream-json event to the session's buffer."""
    buf = _recent_events.get(name)
    if buf is None:
        buf = deque(maxlen=_RECENT_EVENTS_MAX)
        _recent_events[name] = buf
    summary: dict = {"type": event.get("type")}
    subtype = event.get("subtype")
    if subtype:
        summary["subtype"] = subtype
    if event.get("type") == "assistant":
        tools = [
            b.get("name")
            for b in event.get("message", {}).get("content", [])
            if isinstance(b, dict) and b.get("type") == "tool_use"
        ]
        if tools:
            summary["tools"] = tools
    buf.append(summary)


def get_recent_events(name: str) -> list[dict]:
    """Return the recent-event summaries for a session (oldest → newest)."""
    return list(_recent_events.get(name, []))

def _stdout_resets_watchdog(event: dict) -> bool:
    """True only for stdout events that indicate real turn progress.

    Claude emits periodic system/status heartbeats on stdout during long
    silences.  Those must NOT reset the hard-cap watchdog or a frozen turn
    can run indefinitely while the UI shows "Thinking…".
    """
    ev_type = event.get("type")
    if ev_type in ("assistant", "user", "result", "stream_event", "rate_limit_event"):
        return True
    if ev_type == "system" and event.get("subtype") == "init":
        return True
    return False


def _activity_label(tool: str, inp: dict | None) -> tuple[str, str | None]:
    """Map a tool_use block to a human activity label + short detail."""
    inp = inp or {}
    if tool == "Bash":
        return ("Running command", str(inp.get("command", ""))[:80] or None)
    if tool == "Read":
        return ("Reading", str(inp.get("file_path", "")) or None)
    if tool in ("Edit", "Write", "MultiEdit"):
        return ("Editing", str(inp.get("file_path", "")) or None)
    if tool == "Task":
        return ("Sub-agent", str(inp.get("description") or inp.get("prompt", ""))[:80] or None)
    if tool in ("Grep", "Glob"):
        return ("Searching", str(inp.get("pattern", "")) or None)
    if tool == "WebFetch":
        return ("Fetching", str(inp.get("url", "")) or None)
    if tool.startswith("mcp__"):
        server_label, action_label = humanize_tool_name(tool)
        label = f"{server_label} · {action_label}" if action_label else server_label
        return (label, extract_param_preview(tool, inp))
    return (tool, None)


async def _emit_tool_activity(name: str, content: list, q: asyncio.Queue) -> None:
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "tool_use":
            continue
        tool_name = block.get("name", "")
        label, detail = _activity_label(tool_name, block.get("input"))
        if tool_name in sub_agent_tracker.SUB_AGENT_TOOL_NAMES:
            # Sub-agent spawn — handled by sub_agent_tracker; skip generic activity
            continue
        if tool_name == "AskUserQuestion":
            continue
        await q.put(AgentActivity(
            session=name, label=label,
            tool=tool_name, detail=detail,
            call_id=block.get("id"), status="running",
            turn_id=get_current_turn_id(name),
        ))
        set_current_tool(name, label)
        # Propagate ambient tool activity to in-flight sub-agents as phase="activity"
        await sub_agent_tracker.emit_activity_to_in_flight(name, label, q)


def _extract_exit_plan_mode(content: list) -> dict | None:
    """Return the first ExitPlanMode tool_use block found in content, or None."""
    for block in content:
        if (
            isinstance(block, dict)
            and block.get("type") == "tool_use"
            and block.get("name") == "ExitPlanMode"
        ):
            return block
    return None


def _extract_todo_write(content: list) -> dict | None:
    """Return the first TodoWrite tool_use block found in content, or None."""
    for block in content:
        if (
            isinstance(block, dict)
            and block.get("type") == "tool_use"
            and block.get("name") == "TodoWrite"
        ):
            return block
    return None


# Per-session accumulated task list built from TaskCreate/TaskUpdate tool_use
# blocks. Some CLI sessions don't expose TodoWrite at all — the model uses
# TaskCreate{subject, description, activeForm?} + TaskUpdate{taskId, status}
# instead (verified live: "TodoWrite isn't available in this session"). This
# dict reconstructs the same {content, status, activeForm} shape TodoWrite
# would have sent so the panel's TodoUpdate frame/card is agnostic to which
# tool the CLI actually offered.
#
# Keyed by session → provisional taskId → {content, status, activeForm}.
# Persists across turns (the panel replaces its checklist card in place, so
# there is nothing to reset at turn boundaries) and is only cleared when a
# TodoWrite full-list replace arrives for the same session (TodoWrite wins —
# see the `assistant` branch below). Like the other per-session dicts in this
# module (_current_turn_ids, _current_block_index, ...) it is not explicitly
# cleared on session removal; entries are harmless, bounded by session count.
_task_lists: dict[str, dict[str, dict[str, str]]] = {}


def _process_task_blocks(name: str, content: list) -> bool:
    """Fold any TaskCreate/TaskUpdate tool_use blocks into `_task_lists[name]`.

    Returns True when at least one such block was found, so the caller knows
    to emit a TodoUpdate with the freshly accumulated list.
    """
    tasks = _task_lists.setdefault(name, {})
    found = False
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "tool_use":
            continue
        tool_name = block.get("name")
        inp = block.get("input") or {}

        if tool_name == "TaskCreate":
            found = True
            # The CLI assigns ids server-side and does not echo them back on
            # the tool_use block itself — insertion order is used as a
            # provisional key, which matches the CLI's sequential "1", "2", …
            # ids in practice.
            task_id = str(len(tasks) + 1)
            subject = inp.get("subject") or str(inp.get("description") or "")[:80]
            tasks[task_id] = {
                "content": subject,
                "status": "pending",
                "activeForm": inp.get("activeForm") or subject,
            }
        elif tool_name == "TaskUpdate":
            found = True
            task_id = str(inp.get("taskId", ""))
            entry = tasks.get(task_id) or {
                "content": f"Task {task_id}",
                "status": "pending",
                "activeForm": f"Task {task_id}",
            }
            if "status" in inp:
                entry["status"] = inp["status"]
            if "subject" in inp:
                entry["content"] = inp["subject"]
            tasks[task_id] = entry

    return found


def _ordered_task_list(name: str) -> list[dict[str, str]]:
    """`_task_lists[name]` as a list, ordered numerically by taskId when possible."""
    tasks = _task_lists.get(name, {})

    def sort_key(task_id: str) -> tuple[int, str]:
        return (0, task_id.zfill(10)) if task_id.isdigit() else (1, task_id)

    return [tasks[task_id] for task_id in sorted(tasks, key=sort_key)]


def _extract_ask_user_question(content: list) -> dict | None:
    """Return the first AskUserQuestion tool_use block, or None."""
    for block in content:
        if (
            isinstance(block, dict)
            and block.get("type") == "tool_use"
            and block.get("name") == "AskUserQuestion"
        ):
            return block
    return None


def _store_pending(request: PermissionRequest, **extra: object) -> None:
    """Save a superset of the emitted PermissionRequest for send_approval + /pending."""
    entry: dict = {
        "session": request.session,
        "kind": request.kind,
        "title": request.title,
        "description": request.description,
        "options": [o.model_dump() for o in request.options],
        "questions": request.questions,
        "plan_file_path": request.plan_file_path,
        "tool_name": request.tool_name,
        "tool_input": request.tool_input,
        "created_at": time.time(),
    }
    entry.update(extra)
    _pending_permissions[request.request_id] = entry


async def _emit_ask_user_request(name: str, block: dict, q: asyncio.Queue) -> str:
    """Emit a PermissionRequest for AskUserQuestion; return request_id."""
    request_id = str(uuid.uuid4())
    inp = block.get("input") or {}
    questions = inp.get("questions") or []
    summary_lines = [
        f"• {qitem.get('header', '?')}: {qitem.get('question', '')}"
        for qitem in questions
        if isinstance(qitem, dict)
    ]
    request = PermissionRequest(
        session=name,
        request_id=request_id,
        kind="ask_user",
        title="Claude has questions for you",
        description="\n".join(summary_lines) if summary_lines else "Please answer the questions below.",
        questions=questions,
        options=[
            PermissionOption(id="submit", label="Submit answers"),
            PermissionOption(id="deny", label="Skip"),
        ],
    )
    _store_pending(request, tool_use_id=block.get("id"))
    await q.put(request)
    logger.info("Session '%s' AskUserQuestion emitted (request_id=%s)", name, request_id)
    return request_id


async def _emit_tool_blocked_request(
    name: str,
    tool_name: str,
    tool_input: dict,
    error_text: str,
    q: asyncio.Queue,
) -> None:
    """Emit an actionable card when a tool call was blocked inline."""
    request_id = str(uuid.uuid4())
    detail = error_text[:400] if error_text else json.dumps(tool_input)[:400]
    request = PermissionRequest(
        session=name,
        request_id=request_id,
        kind="tool_blocked",
        title=f"Tool blocked: {tool_name}",
        description=detail,
        tool_name=tool_name,
        tool_input=tool_input,
        options=[
            PermissionOption(id="allow_always", label="Always allow"),
            PermissionOption(id="allow_once", label="Allow once"),
            PermissionOption(id="skip", label="Skip"),
        ],
    )
    _store_pending(request)
    await q.put(request)


async def _emit_plan_permission_request(
    name: str, block: dict, q: asyncio.Queue
) -> str:
    """Emit a PermissionRequest for a detected ExitPlanMode tool_use.

    Returns the request_id so the caller can track the pending request.
    """
    request_id = str(uuid.uuid4())
    inp = block.get("input") or {}
    plan_text = inp.get("plan", "")
    plan_file = inp.get("planFilePath")

    request = PermissionRequest(
        session=name,
        request_id=request_id,
        kind="plan",
        title="Plan ready — approve to proceed?",
        description=plan_text,
        plan_file_path=plan_file,
        options=[
            PermissionOption(id="approve", label="Approve & proceed"),
            PermissionOption(id="deny", label="Revise plan"),
        ],
    )
    _store_pending(request)
    await q.put(request)
    logger.info(
        "Session '%s' plan permission request emitted (request_id=%s)", name, request_id,
    )
    return request_id


async def _emit_permission_denied_notices(
    name: str, denials: list, q: asyncio.Queue
) -> None:
    """Emit informational PermissionRequest frames for auto-blocked tool calls.

    These are NOT actionable — no approval can be sent in print/stream-json
    mode for per-tool permission prompts.  They exist so the UI can show what
    was blocked rather than silently showing a completed turn.
    """
    for denial in denials:
        tool_name = denial.get("tool_name", "unknown tool")
        tool_input = denial.get("tool_input", {})
        request_id = str(uuid.uuid4())
        await q.put(PermissionRequest(
            session=name,
            request_id=request_id,
            kind="permission_denied",
            title=f"Permission denied: {tool_name}",
            description=(
                f"The tool call '{tool_name}' was blocked by the sandbox "
                f"and could not be approved interactively in headless mode. "
                f"Input: {json.dumps(tool_input)[:300]}"
            ),
            options=[],  # no approval possible
        ))
    if denials:
        logger.info(
            "Session '%s' emitted %d permission_denied notice(s)", name, len(denials),
        )


async def dispatch_event(
    name: str,
    event: dict,
    q: asyncio.Queue,
    *,
    is_first_message: bool,
) -> bool:
    """Process one stream-json event; return True when the turn is complete.

    is_first_message: True only for the very first turn of a session.
    On subsequent turns the process re-emits system/init with the same
    session_id — we update the store but suppress the duplicate SessionReady
    frame so callers see exactly one SessionReady per process lifetime.

    result subtypes handled: success, error, error_max_turns, and any future
    subtypes — all emit AiDone (is_error subtypes carry exit_code=1).

    Permission events (plan mode):
    When an assistant event contains an ExitPlanMode tool_use block, a
    PermissionRequest(kind="plan") is emitted immediately so the UI can surface
    the plan and prompt for approval.  The turn still ends normally with
    AiDone after the result event — the turn is NOT suppressed, because the
    approval is sent as a new turn via session_manager.send_approval().
    """
    ev_type = event.get("type", "")

    if ev_type == "system" and event.get("subtype") == "init":
        sid = event.get("session_id", "")
        if is_first_message:
            resumed = bool(session_store.get_session(name))
            session_store.upsert_session(name, sid)
            await q.put(SessionReady(session=name, session_id=sid, resumed=resumed))
        else:
            session_store.upsert_session(name, sid)

    elif ev_type == "stream_event":
        inner = event.get("event", {})
        if inner.get("type") == "content_block_start":
            block = inner.get("content_block", {}) or {}
            if block.get("type") == "text":
                next_index = _text_block_counters.get(name, 0) + 1
                _text_block_counters[name] = next_index
                _current_block_index[name] = next_index
        delta = inner.get("delta", {})
        if delta.get("type") == "text_delta":
            text = delta.get("text", "")
            if text:
                await q.put(AiChunk(
                    session=name, text=text,
                    turn_id=get_current_turn_id(name),
                    block_index=_current_block_index.get(name, 0),
                ))
                # A9: accumulate so the full reply can be persisted to the
                # bridge transcript on `result` — the Claude path never wrote
                # assistant turns there, leaving transcript reads after a
                # session_id loss with questions but no answers.
                _accumulate_assistant_text(name, text)
        elif delta.get("type") == "thinking_delta":
            thinking_text = delta.get("thinking", "")
            if thinking_text:
                await q.put(ThinkingChunk(
                    session=name, text=thinking_text,
                    turn_id=get_current_turn_id(name),
                ))
        # Surface thinking blocks as a live activity label (extended thinking mode).
        await _lfh.emit_thinking_activity(name, inner, q)

    elif ev_type == "assistant":
        content = event.get("message", {}).get("content", [])
        # Register tool_use_id → tool_name for result linking before activity.
        _lfh.register_pending_tool_calls(name, content)
        # Emit SubAgent(phase='start') for Task blocks before generic activity.
        task_blocks = sub_agent_tracker.extract_task_blocks(content)
        if task_blocks:
            await sub_agent_tracker.emit_sub_agent_starts(name, task_blocks, q)
        await _emit_tool_activity(name, content, q)
        # Detect plan-mode approval gate: ExitPlanMode tool_use signals that
        # claude has a plan ready and is waiting for human approval to proceed.
        exit_plan_block = _extract_exit_plan_mode(content)
        if exit_plan_block is not None:
            await _emit_plan_permission_request(name, exit_plan_block, q)
        ask_block = _extract_ask_user_question(content)
        if ask_block is not None:
            await _emit_ask_user_request(name, ask_block, q)
        # Live todo checklist: TodoWrite calls carry the agent's current plan
        # state — emit a dedicated frame (in addition to the generic
        # AgentActivity row above) so the panel can render a live checklist.
        todo_block = _extract_todo_write(content)
        if todo_block is not None:
            todos = (todo_block.get("input") or {}).get("todos", [])
            # TodoWrite wins: a full-list replace supersedes any task list
            # accumulated from TaskCreate/TaskUpdate for this session.
            _task_lists.pop(name, None)
            await q.put(TodoUpdate(
                session=name, turn_id=get_current_turn_id(name), todos=todos,
            ))
        elif _process_task_blocks(name, content):
            # This CLI session doesn't expose TodoWrite — it used
            # TaskCreate/TaskUpdate instead. Emit the same TodoUpdate frame
            # from the accumulated task list so the panel is unaffected.
            await q.put(TodoUpdate(
                session=name, turn_id=get_current_turn_id(name),
                todos=_ordered_task_list(name),
            ))

    elif ev_type == "user":
        # Check for tool_result content that corresponds to completed sub-agents.
        user_content = event.get("message", {}).get("content", [])
        if user_content:
            # Sub-agent completions first (they consume matching tool_use_ids).
            await sub_agent_tracker.handle_tool_results(name, user_content, q)
            # Emit short summaries for all other (non-sub-agent) tool results.
            await _lfh.emit_tool_result_summaries(name, user_content, q)
            # A3: the tool that was "current" has a result now — clear it.
            # Best-effort (doesn't track which of several parallel tools
            # finished), same approximation already used by sub_agent_tracker.
            if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in user_content):
                set_current_tool(name, None)
            # Inline tool denials (default permission mode) — offer retry with bypass.
            for block in user_content:
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                if not block.get("is_error"):
                    continue
                tool_use_id = block.get("tool_use_id", "")
                pending = _lfh.get_pending_tool_call(name, tool_use_id)
                if not pending:
                    continue
                tool_name = pending.get("name", "tool")
                if tool_name in ("ExitPlanMode", "AskUserQuestion"):
                    continue
                tool_input = pending.get("input") or {}
                err_text = block.get("content", "")
                if isinstance(err_text, list):
                    err_text = " ".join(
                        str(p.get("text", p)) if isinstance(p, dict) else str(p)
                        for p in err_text
                    )
                # Lazy import to avoid circular dependency (mirrors watchdog_medic pattern).
                from devscope_bridge import session_manager as _sm
                if _sm.is_bypass_all_tools(name):
                    asyncio.ensure_future(
                        _sm.auto_approve_tool_blocked(name, tool_name, tool_input)
                    )
                else:
                    await _emit_tool_blocked_request(
                        name, tool_name, tool_input, str(err_text), q,
                    )

    elif ev_type == "result":
        # End-of-turn marker; the process stays alive.
        # All subtypes (success, error, error_max_turns, …) signal turn end.
        subtype = event.get("subtype", "")
        is_error_turn = event.get("is_error", False) or subtype not in ("success", "")
        exit_code = 1 if is_error_turn else 0

        # Emit informational notices for auto-blocked tool calls (default mode).
        # These are NOT actionable — just informational.
        denials = event.get("permission_denials") or []
        # ExitPlanMode and AskUserQuestion are auto-denied in --print mode, but
        # both are ALREADY surfaced as actionable cards (kind="plan" / "ask_user")
        # from the assistant event.  Suppress their redundant "permission_denied"
        # notices so the user doesn't see a scary "Permission denied: AskUserQuestion"
        # on top of the question card they can actually answer.
        _SURFACED_ELSEWHERE = ("ExitPlanMode", "AskUserQuestion")
        unsurfaced_denials = [
            d for d in denials if d.get("tool_name") not in _SURFACED_ELSEWHERE
        ]
        if unsurfaced_denials:
            await _emit_permission_denied_notices(name, unsurfaced_denials, q)

        usage = event.get("usage", {}) or {}
        input_tokens = int(usage.get("input_tokens", 0) or 0)
        tokens = input_tokens + int(usage.get("output_tokens", 0) or 0)
        accumulate_usage(name, event)
        turn_id = get_current_turn_id(name)
        duration_ms = int(event.get("duration_ms", 0) or 0)
        cost_usd = float(event.get("total_cost_usd", 0) or 0)
        model = event.get("model")
        if not model:
            model_usage = event.get("modelUsage")
            if isinstance(model_usage, dict) and model_usage:
                model = next(iter(model_usage.keys()), None)
        await q.put(TurnResult(
            session=name,
            turn_id=turn_id,
            duration_ms=duration_ms,
            cost_usd=cost_usd,
            input_tokens=input_tokens,
            output_tokens=int(usage.get("output_tokens", 0) or 0),
            model=model,
        ))
        await q.put(Usage(
            session=name,
            tokens=tokens,
            cost_usd=cost_usd,
            duration_ms=duration_ms,
            input_tokens=input_tokens,
        ))
        from devscope_bridge import chat_session_hygiene
        asyncio.create_task(chat_session_hygiene.evaluate_after_turn(name, q, input_tokens))

        # Clear per-turn tracking state.
        sub_agent_tracker.clear_session(name)
        _lfh.clear_pending_tool_calls(name)
        set_current_tool(name, None)
        _current_block_index.pop(name, None)
        _text_block_counters.pop(name, None)

        # A9: persist the full assistant reply to the bridge transcript so a
        # later read (after session_id loss) has user+assistant pairs, not
        # just the user side. The Claude JSONL stays the preferred read
        # source when it exists — this only enriches the fallback.
        assistant_text = _consume_assistant_text(name)
        if assistant_text.strip():
            session_store.append_bridge_turn(name, "assistant", assistant_text)

        if is_error_turn:
            result_text = str(event.get("result", "") or "")
            await q.put(AiError(
                session=name, exit_code=exit_code,
                stderr_tail=result_text[:500],
            ))
        else:
            await q.put(AiDone(session=name, exit_code=0, turn_id=turn_id))
        await q.put(TurnState(session=name, running=False, turn_id=turn_id))
        return True

    elif ev_type == "system" and event.get("subtype") == "api_retry":
        await q.put(RateLimit(session=name, retry_ms=event.get("retry_delay_ms", 4000)))

    else:
        logger.debug("Unhandled event type '%s' from session '%s'", ev_type, name)

    return False


async def _maybe_emit_heartbeat(
    q: asyncio.Queue, name: str, turn_elapsed: float, silence_elapsed: float,
    next_heartbeat_at: float,
) -> float:
    """Periodic 'still working' ping every _WATCHDOG_HEARTBEAT_S of turn time.

    A4 fix (RC-1): driven by turn_elapsed, NOT by silence — the old code reset
    its one-shot latch on every stdout event, so a trickling turn (occasional
    output that keeps resetting silence) never accumulated enough CONTINUOUS
    silence to re-fire and went quiet until the 2400s wall cap. Returns the
    next turn_elapsed threshold at which to fire again.
    """
    if turn_elapsed < next_heartbeat_at:
        return next_heartbeat_at
    await q.put(AgentActivity(
        session=name,
        label="still working…",
        detail=f"Turn running {turn_elapsed:.0f}s (last output {silence_elapsed:.0f}s ago)",
    ))
    return next_heartbeat_at + _WATCHDOG_HEARTBEAT_S


async def _maybe_emit_soft_wall_warning(
    q: asyncio.Queue, name: str, turn_elapsed: float, already_warned: bool,
) -> bool:
    """One-shot, non-destructive notice at the _WATCHDOG_SOFT_WALL_S mark."""
    if already_warned or turn_elapsed < _WATCHDOG_SOFT_WALL_S:
        return already_warned
    await q.put(AgentActivity(
        session=name,
        label="⏱ Turn running 10m+",
        detail="Still going — Stop or /medic is available if this looks stuck.",
    ))
    return True


async def _maybe_warn_steering_stall(
    q: asyncio.Queue,
    name: str,
    pending_prompts_fn: Callable[[], int] | None,
    stall_elapsed: float,
    already_warned: bool,
    tick: float,
) -> tuple[float, bool]:
    """A8: warn once if a mid-turn (steering) message never started a new turn.

    Runs only while the session is IDLE (turn_active_event clear) — the old
    guard froze ALL timers between turns, so a steering write that the CLI
    never picked up as a new turn went unnoticed forever instead of surfacing
    within _STEERING_STALL_S (RC-7).
    """
    if pending_prompts_fn is None or pending_prompts_fn() <= 0:
        return 0.0, False
    stall_elapsed += tick
    if stall_elapsed >= _STEERING_STALL_S and not already_warned:
        await q.put(AgentActivity(
            session=name,
            label="⚠ Steering message may have been dropped",
            detail="No new turn started within 120s of your message — resend or Stop.",
            status="error",
        ))
        already_warned = True
    return stall_elapsed, already_warned


def compute_hard_due(
    silence_due: bool,
    wall_due: bool,
    absolute_due: bool,
    *,
    long_running: bool,
    subagents_in_flight: bool,
) -> bool:
    """Decide which caps may hard-interrupt the current turn (pure helper).

    - subagents_in_flight: a parent waiting on Task/Agent sub-agents is
      legitimately long AND often silent — only the absolute ceiling applies.
    - long_running: silence-exempt orchestrator workers; wall + absolute apply.
    - default: any cap fires.
    """
    if subagents_in_flight:
        return absolute_due
    if long_running:
        return wall_due or absolute_due
    return silence_due or wall_due or absolute_due


async def _watchdog_loop(
    name: str,
    q: asyncio.Queue,
    activity_event: asyncio.Event,
    hard_interrupt_fn: Callable[[], None] | None = None,
    turn_active_event: asyncio.Event | None = None,
    medic_fn: Callable[[float], None] | None = None,
    medic_active: asyncio.Event | None = None,
    pending_prompts_fn: Callable[[], int] | None = None,
) -> None:
    """Emit heartbeat/medic/guidance frames when a turn goes silent too long.

    Independent thresholds:
    - _WATCHDOG_HEARTBEAT_S: periodic AgentActivity("still working…"), driven
      by turn_elapsed so it survives a trickling turn (see _maybe_emit_heartbeat).
    - _WATCHDOG_SOFT_WALL_S: one-shot "turn running 10m+" hint.
    - _WATCHDOG_MEDIC_S: call medic_fn(elapsed) to spawn the Watchdog Medic — a
      SEPARATE diagnostic agent that investigates the live, still-stuck process
      and reports to the panel.  This runs BEFORE the destructive hard cap so
      the stuck process is still alive to inspect.
    - _WATCHDOG_HARD_CAP_S: emit AiError and call hard_interrupt_fn so the
      session manager can SIGINT + respawn the process, guaranteeing the UI
      always unblocks.  DEFERRED while a medic is running (medic_active set) so
      the medic is not killing the process it is still diagnosing.
    - _STEERING_STALL_S (A8): while IDLE, if pending_prompts_fn() > 0 (a
      steering message was written mid-turn) and no new turn starts, warn once.

    hard_interrupt_fn / medic_fn: called synchronously (not awaited) from the
    event loop; both only schedule background work, so neither blocks the loop.

    turn_active_event: when provided, the watchdog only counts elapsed time
    while this event is set (turn in progress).  Between turns (event clear),
    elapsed resets to zero — prevents false-positive hard-caps during idle
    periods and after forced respawns before the next message arrives. The
    steering-stall check is the one thing that still runs during this idle
    window (see A8: the old guard froze it along with everything else).

    The tick adapts to the heartbeat threshold so the loop stays responsive
    when thresholds are shortened (e.g. in tests), capped at 10s for prod.
    """
    tick = min(10.0, max(0.05, _WATCHDOG_HEARTBEAT_S / 2))
    silence_elapsed = 0.0
    turn_elapsed = 0.0
    next_heartbeat_at = _WATCHDOG_HEARTBEAT_S
    wall_warned = False
    medic_triggered = False
    hard_cap_triggered = False
    medic_defer_elapsed = 0.0
    steering_stall_elapsed = 0.0
    steering_warned = False
    while True:
        await asyncio.sleep(tick)

        # Between turns: freeze timers so idle process is never killed.
        if turn_active_event is not None and not turn_active_event.is_set():
            silence_elapsed = 0.0
            turn_elapsed = 0.0
            next_heartbeat_at = _WATCHDOG_HEARTBEAT_S
            wall_warned = False
            medic_triggered = False
            hard_cap_triggered = False
            medic_defer_elapsed = 0.0
            steering_stall_elapsed, steering_warned = await _maybe_warn_steering_stall(
                q, name, pending_prompts_fn, steering_stall_elapsed, steering_warned, tick,
            )
            continue
        steering_stall_elapsed = 0.0
        steering_warned = False

        silence_elapsed += tick
        turn_elapsed += tick
        if activity_event.is_set():
            # Reset silence only — do NOT skip wall/absolute checks below.
            # Trickle stream_event tokens used to `continue` here and forever
            # skip the turn wall-cap → overnight ghost "Working…" turns.
            activity_event.clear()
            silence_elapsed = 0.0

        next_heartbeat_at = await _maybe_emit_heartbeat(
            q, name, turn_elapsed, silence_elapsed, next_heartbeat_at,
        )
        wall_warned = await _maybe_emit_soft_wall_warning(q, name, turn_elapsed, wall_warned)

        medic_due = (
            silence_elapsed >= _WATCHDOG_MEDIC_S
            or turn_elapsed >= _WATCHDOG_TURN_WALL_MEDIC_S
        )
        if medic_due and not medic_triggered and medic_fn is not None:
            medic_triggered = True
            trigger_elapsed = max(silence_elapsed, turn_elapsed)
            reason = (
                f"silent {silence_elapsed:.0f}s"
                if silence_elapsed >= _WATCHDOG_MEDIC_S
                else f"turn wall {turn_elapsed:.0f}s"
            )
            logger.warning(
                "Session '%s' medic trigger (%s) — dispatching Watchdog Medic",
                name, reason,
            )
            medic_fn(trigger_elapsed)

        silence_due = silence_elapsed >= _WATCHDOG_HARD_CAP_S
        wall_due = turn_elapsed >= _WATCHDOG_TURN_WALL_CAP_S
        absolute_due = turn_elapsed >= _WATCHDOG_TURN_ABSOLUTE_CAP_S
        # Live Task/Agent sub-agents exempt the turn from silence AND wall
        # caps — a parent waiting on children is legitimately long and often
        # silent. Orchestrator long_running workers skip silence only.
        # The absolute ceiling always applies.
        hard_due = compute_hard_due(
            silence_due, wall_due, absolute_due,
            long_running=is_long_running(name),
            subagents_in_flight=sub_agent_tracker.has_in_flight(name),
        )
        if hard_due and not hard_cap_triggered:
            # Defer while medic diagnoses — but never longer than DEFER_MAX,
            # and never past the absolute turn ceiling.
            if (
                medic_active is not None
                and medic_active.is_set()
                and not absolute_due
                and medic_defer_elapsed < _WATCHDOG_MEDIC_DEFER_MAX_S
            ):
                medic_defer_elapsed += tick
                continue
            hard_cap_triggered = True
            trigger_elapsed = max(silence_elapsed, turn_elapsed)
            if absolute_due:
                reason = f"turn exceeded absolute cap {turn_elapsed:.0f}s"
            elif wall_due:
                reason = f"turn exceeded {turn_elapsed:.0f}s"
            else:
                reason = f"no output for {silence_elapsed:.0f}s"
            logger.warning(
                "Session '%s' hard-timeout (%s) — emitting AiError + interrupting",
                name, reason,
            )
            await q.put(AiError(
                session=name,
                exit_code=-1,
                stderr_tail=(
                    f"[bridge] Turn appears stuck: {reason}. "
                    "Interrupting and respawning. Please retry your last message."
                ),
            ))
            if hard_interrupt_fn is not None:
                hard_interrupt_fn()


async def continuous_reader(
    name: str,
    proc: asyncio.subprocess.Process,
    q: asyncio.Queue,
    turn_complete_event: asyncio.Event | None = None,
    hard_interrupt_fn: Callable[[], None] | None = None,
    pending_prompts_fn: Callable[[], int] | None = None,
) -> None:
    """Read stdout continuously; route each line to dispatch_event.

    pending_prompts_fn: returns the session's current steering-message count
    (session_manager._ActiveSession.pending_prompts) — the A8 watchdog check
    reads it to warn when a mid-turn message never started a new turn.

    Tracks turn number to suppress duplicate SessionReady frames after the
    first turn.  Emits AiError when the process exits unexpectedly.

    Two-tier watchdog: heartbeat at _WATCHDOG_HEARTBEAT_S (AgentActivity);
    hard cap at _WATCHDOG_HARD_CAP_S (AiError + hard_interrupt_fn call).
    The hard cap guarantees the UI always unblocks even on a frozen turn.

    Watchdog is turn-aware: it only counts elapsed silence while a turn is
    ACTIVE.  Between turns the timer is frozen — a healthy persistent process
    sitting idle between messages is never killed by the hard-cap.  This
    prevents false-positive kills after forced respawns.

    Official CLI docs confirm: stdout goes COMPLETELY SILENT during tool
    execution (Bash, Read, MCP tools).  The 300s hard cap is calibrated to
    accommodate long tool runs, not short inter-token gaps.

    turn_complete_event: set on every turn end.
    hard_interrupt_fn: called (not awaited) when hard cap fires.
    Post-exit AiError suppression: hard-cap already emitted one AiError;
    process-exit AiError is suppressed to avoid duplicates on the queue.
    """
    assert proc.stdout is not None
    turn_count = 0
    activity_event = asyncio.Event()
    # Set when the hard-cap fires so we can suppress the redundant post-exit AiError.
    hard_cap_fired = asyncio.Event()
    # Set for the lifetime of a Watchdog Medic run so the hard cap defers.
    medic_active = asyncio.Event()
    # SET while a turn is running, CLEAR between turns.  Watchdog counts only
    # when set; idle periods never trigger the hard-cap.
    turn_is_running = (
        turn_complete_event is not None and not turn_complete_event.is_set()
    )
    turn_active_event = asyncio.Event()
    if turn_is_running:
        turn_active_event.set()

    def _wrapped_hard_interrupt_fn() -> None:
        hard_cap_fired.set()
        if hard_interrupt_fn is not None:
            hard_interrupt_fn()

    def _medic_fn(elapsed_s: float) -> None:
        # Lazy import: watchdog_medic imports session_manager which imports this
        # module — importing at call time avoids the import cycle.
        from devscope_bridge import watchdog_medic
        asyncio.ensure_future(watchdog_medic.run_medic(name, q, medic_active, elapsed_s))

    watchdog = asyncio.create_task(
        _watchdog_loop(
            name, q, activity_event,
            hard_interrupt_fn=_wrapped_hard_interrupt_fn,
            turn_active_event=turn_active_event,
            medic_fn=_medic_fn,
            medic_active=medic_active,
            pending_prompts_fn=pending_prompts_fn,
        )
    )

    try:
        async for raw in proc.stdout:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                logger.debug("Non-JSON stdout line from '%s': %s", name, line[:120])
                continue

            record_recent_event(name, event)

            if _stdout_resets_watchdog(event):
                if not turn_active_event.is_set():
                    # A8: this stdout marks a NEW turn starting — one fewer
                    # steering message waiting on the CLI to pick it up.
                    from devscope_bridge import session_manager as _sm
                    _sm.decrement_pending_prompts(name)
                touch_output(name)
                activity_event.set()
                turn_active_event.set()  # turn is live

            is_first = (turn_count == 0)
            turn_ended = await dispatch_event(name, event, q, is_first_message=is_first)
            if turn_ended:
                turn_count += 1
                turn_active_event.clear()  # pause watchdog between turns
                if turn_complete_event is not None:
                    turn_complete_event.set()
                # A message deferred mid-turn (sub-agents were in flight) can
                # now start its own turn. Lazy import mirrors the
                # session_manager cycle-avoidance pattern above.
                from devscope_bridge import session_manager as _sm
                await _sm.flush_deferred_message(name)
    finally:
        watchdog.cancel()
        # Process exit / cancel without a result event used to leave turn_done
        # clear forever → UI queues messages overnight. Always free the turn.
        turn_active_event.clear()
        # Drop any partial assistant text from a turn that never reached
        # `result` — persisting a truncated fragment would be worse than
        # nothing, and it must not bleed into the NEXT turn's accumulation.
        _consume_assistant_text(name)
        if turn_complete_event is not None and not turn_complete_event.is_set():
            turn_complete_event.set()
            try:
                await q.put(TurnState(session=name, running=False))
            except Exception:  # noqa: BLE001 — never block reader teardown
                pass

    # Process exited — only emit AiError when it was not caused by the hard-cap
    # watchdog (which already emitted one).  Hard-cap-induced exits are intentional;
    # a second AiError would confuse the UI and partially drain the out_queue.
    if hard_cap_fired.is_set():
        logger.debug(
            "Session '%s' proc exited after hard-cap — suppressing duplicate AiError", name,
        )
        return
    exit_code = await proc.wait()
    # NOT `await proc.stderr.read()` — session_manager._drain_stderr is the
    # sole consumer of proc.stderr (StreamReader supports only one reader);
    # by the time the process has exited, drain has already collected the
    # tail into this session's buffer.
    tail = get_stderr_tail(name)
    await q.put(AiError(session=name, exit_code=exit_code, stderr_tail=tail))
