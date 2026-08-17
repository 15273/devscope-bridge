"""
session_manager.py — Manages persistent agent CLI subprocesses.

Supports two agents:
- "claude" : ONE persistent process per session using stream-json I/O.
- "cursor"  : blocking subprocess per call, delegated to session_manager_cursor.

Registry / spawn / recovery live in session_runtime, session_lifecycle,
and session_recovery. This module keeps run_prompt + approvals so existing
test monkeypatches on session_manager.* still apply.
"""

import asyncio
import json
import logging
import os
import signal
import uuid
from datetime import datetime

from devscope_bridge import session_store
from devscope_bridge import session_manager_cursor
from devscope_bridge import session_reader
from devscope_bridge import sub_agent_tracker
from devscope_bridge.context_builder import build_context_preamble, extract_image_blocks
from devscope_bridge.models import (
    AgentActivity, AiDone, AiError, ContextRecovery, MessageContext, TurnState,
)
from devscope_bridge.session_lifecycle import (
    _idle_eviction,
    _make_hard_interrupt_fn,
    _make_pending_prompts_fn,
    _needs_respawn,
    _respawn_process,
    _spawn_claude_proc,
    _terminate_session,
    _build_claude_args,
    _drain_stderr,
    _force_turn_idle,
    _terminate_process_only,
    start_stale_turn_sweeper,
    stop_stale_turn_sweeper,
)
from devscope_bridge.session_recovery import (
    _PREAMBLE_USER_MSG_SEPARATOR,
    _cursor_needs_recovery_preamble,
    _encode_user_message,
    build_recovery_preamble,
)
from devscope_bridge.session_runtime import (
    DEFAULT_CWD,
    _ActiveSession,
    _INTERRUPT_GRACE_S,
    _out_queues,
    _session_agent,
    _session_claude_agent,
    _session_cwd,
    _session_mode,
    _session_model,
    _sessions,
    decrement_pending_prompts,
    forget_out_queue,
    get_or_create_out_queue,
    subscription_env,
)

logger = logging.getLogger(__name__)

async def _queue_deferred_message(
    active: _ActiveSession, full_prompt: str, image_blocks: list[dict],
) -> None:
    """Park a mid-turn message while Task/Agent sub-agents are in flight.

    A mid-turn stdin write is treated by the CLI as an interrupt and aborts
    in-flight sub-agents. flush_deferred_message() dispatches the message as a
    fresh turn once the current turn ends.
    """
    active.deferred_messages.append((full_prompt, image_blocks))
    active.deferred_pid = active.proc.pid
    logger.info(
        "Session '%s' message deferred mid-turn (sub-agents in flight, queued=%d)",
        active.name, len(active.deferred_messages),
    )
    await active.out_queue.put(AgentActivity(
        session=active.name,
        label="Message queued",
        detail=(
            "Sub-agents are still running — your message will start a new "
            "turn as soon as the current one finishes."
        ),
    ))


async def flush_deferred_message(name: str) -> None:
    """Dispatch the FIRST message deferred mid-turn, as a new turn.

    Called by session_reader.continuous_reader right after the CLI `result`
    event marks the turn done. Drops the whole queue with a warning when the
    process died or was respawned since the defer — the panel already resends
    failed messages.
    """
    active = _sessions.get(name)
    if active is None or not active.deferred_messages:
        return
    proc_gone = (
        active.proc.returncode is not None
        or active.proc.pid != active.deferred_pid
        or active.proc.stdin is None
    )
    if proc_gone:
        dropped = len(active.deferred_messages)
        active.deferred_messages.clear()
        logger.warning(
            "Session '%s' dropped %d deferred message(s) — process died/respawned before flush",
            name, dropped,
        )
        return
    full_prompt, image_blocks = active.deferred_messages.pop(0)
    turn_id = uuid.uuid4().hex[:12]
    session_reader.set_current_turn_id(name, turn_id)
    active.turn_done.clear()
    active.turn_started_at = datetime.now()
    await active.out_queue.put(TurnState(session=name, running=True, turn_id=turn_id))
    active.proc.stdin.write(_encode_user_message(full_prompt, image_blocks))
    await active.proc.stdin.drain()
    logger.info("Session '%s' deferred message flushed as new turn %s", name, turn_id)


async def run_prompt(
    name: str,
    prompt: str,
    mode: str | None = None,
    model: str | None = None,
    context: MessageContext | None = None,
) -> asyncio.Queue:
    """Dispatch prompt for session `name`, routing by agent type.

    Reuses the persistent Claude process when mode/model are unchanged;
    respawns with --resume on mode/model change or dead proc.  The out_queue
    is STABLE (never replaced); callers must use a pump task, not block-drain.
    """
    stored = session_store.get_session(name)
    prior_session_id = stored["session_id"] if stored else None
    agent = _session_agent(name)
    cwd = _session_cwd(name)
    effective_mode = mode or _session_mode(name)
    effective_model = model or _session_model(name)
    effective_claude_agent = _session_claude_agent(name)

    from devscope_bridge import builtin_commands as _builtins
    from devscope_bridge import session_hygiene as _hygiene
    from devscope_bridge.mode_presets import cursor_browser_prompt_suffix

    automation_turn = _hygiene.is_automation_session(name, stored)
    if automation_turn:
        prior_session_id = None

    # Single consumer for /compact and auto-compact preambles (Cursor + Claude).
    compact_pre = _builtins.pending_compact_preambles.pop(name, None)

    preamble = build_context_preamble(context)
    full_prompt = preamble + prompt if preamble else prompt
    image_blocks = extract_image_blocks(context)

    if agent == "cursor":
        cursor_resume_id = None if automation_turn else (prior_session_id or None)
        if compact_pre:
            full_prompt = compact_pre + _PREAMBLE_USER_MSG_SEPARATOR + full_prompt
            logger.info("Session '%s' → Cursor compact preamble injected", name)
        browser_suffix = cursor_browser_prompt_suffix(
            has_bound_tab=bool(context and context.boundTab),
            mode=effective_mode,
        )
        if browser_suffix:
            full_prompt = browser_suffix + "\n\n" + full_prompt
        # Automation turns carry full digest in prompt — no transcript recovery.
        if (
            not automation_turn
            and not compact_pre
            and _cursor_needs_recovery_preamble(prompt, prior_session_id)
        ):
            recovery = build_recovery_preamble(name)
            if recovery:
                full_prompt = recovery + "\n\n---\n\n" + full_prompt
                logger.info(
                    "Session '%s' → Cursor recovery preamble injected (chatId=%s)",
                    name,
                    "yes" if prior_session_id else "no",
                )
        session_store.append_bridge_turn(name, "user", prompt)
        logger.info(
            "Session '%s' → Cursor (cwd=%s mode=%s resume=%s)",
            name, cwd, effective_mode, "no" if automation_turn else bool(cursor_resume_id),
        )
        return await session_manager_cursor.dispatch_cursor(
            name, full_prompt, cursor_resume_id, cwd,
            mode=effective_mode, model=effective_model,
        )

    # ── Claude persistent path ──────────────────────────────────────────
    # Terminal-first chat: when a chat-* PTY owns this session, messages go
    # through the interactive CLI — never spawn a competing headless process.
    from devscope_bridge import pty_manager
    from devscope_bridge.models import TurnState

    live_pty = pty_manager.terminal_for_session(name)
    if live_pty and live_pty.startswith("chat-"):
        logger.info(
            "run_prompt: chat PTY '%s' owns '%s' — skipping headless spawn",
            live_pty, name,
        )
        skip_q: asyncio.Queue = asyncio.Queue()
        await skip_q.put(TurnState(session=name, running=False))
        return skip_q

    # Single-owner guarantee: if a PTY terminal is live on this session, close it
    # first.  Otherwise two `claude --resume <same id>` processes (PTY + chat)
    # race on the same conversation and the second one hangs.  Lazy import avoids
    # the pty_manager ↔ session_manager import cycle.
    if live_pty:
        logger.warning("run_prompt: closing live PTY '%s' before chat spawn for '%s'", live_pty, name)
        pty_manager.close_terminal(live_pty)
        # The terminal advanced the conversation; any surviving chat process is
        # now stale (its in-memory history predates the terminal's turns).  Drop
        # it so we respawn fresh with --resume and pick up those turns.
        await kill_session(name)

    active = _sessions.get(name)

    if active is None:
        proc = await _spawn_claude_proc(
            prior_session_id, cwd, mode=effective_mode, model=effective_model,
            session_name=name,
        )
        # A1: reuse the persistent registry queue — never a fresh asyncio.Queue()
        # here, or a WS pump that attached before this spawn (main.py resolves
        # the same registry) would be bound to a different, orphaned object.
        q: asyncio.Queue = get_or_create_out_queue(name)
        turn_done = asyncio.Event()
        turn_done.set()  # idle until the first message clears it
        _sessions[name] = _ActiveSession(
            name=name, session_id=prior_session_id or "",
            proc=proc, out_queue=q,
            reader_task=asyncio.create_task(
                session_reader.continuous_reader(
                    name, proc, q, turn_done,
                    hard_interrupt_fn=_make_hard_interrupt_fn(name),
                    pending_prompts_fn=_make_pending_prompts_fn(name),
                )
            ),
            idle_task=asyncio.create_task(_idle_eviction(name)),
            mode=effective_mode, model=effective_model,
            claude_agent=effective_claude_agent,
            turn_done=turn_done,
        )
        logger.info(
            "Session '%s' → Claude persistent (pid=%d cwd=%s mode=%s model=%s agent=%s)",
            name, proc.pid, cwd, effective_mode, effective_model, effective_claude_agent,
        )

    elif _needs_respawn(active, effective_mode, effective_model, effective_claude_agent):
        # Keep permanent tool bypass across mode/model respawns.
        override = "bypassPermissions" if active.bypass_all_tools else None
        await _respawn_process(
            active, prior_session_id, cwd, effective_mode, effective_model,
            permission_mode_override=override,
            claude_agent=effective_claude_agent,
        )

    else:
        logger.info("Session '%s' reusing persistent process (pid %d)", name, active.proc.pid)

    active_session = _sessions[name]
    assert active_session.proc.stdin is not None
    session_store.append_bridge_turn(name, "user", prompt)
    # A mid-turn message while Task/Agent sub-agents are in flight must NOT be
    # written to stdin (the CLI treats it as an interrupt and aborts the
    # sub-agents). Queue it; session_reader flushes it at turn end. Plain
    # steering (no sub-agents) keeps the A8 write-through behavior below.
    if not active_session.turn_done.is_set() and sub_agent_tracker.has_in_flight(name):
        if compact_pre:
            _builtins.pending_compact_preambles[name] = compact_pre  # re-queue unconsumed
        await _queue_deferred_message(active_session, full_prompt, image_blocks)
        return active_session.out_queue
    turn_id = uuid.uuid4().hex[:12]
    session_reader.set_current_turn_id(name, turn_id)
    # /compact, auto-compact, or respawn recovery — merge into one injection.
    if compact_pre:
        active_session.pending_preamble = (
            (compact_pre + "\n\n---\n\n" + active_session.pending_preamble)
            if active_session.pending_preamble
            else compact_pre
        )
        logger.info("Session '%s' → Claude compact preamble queued", name)
    if active_session.pending_preamble:
        full_prompt = active_session.pending_preamble + _PREAMBLE_USER_MSG_SEPARATOR + full_prompt
        active_session.pending_preamble = None
        await active_session.out_queue.put(ContextRecovery(
            session=name, detail="Context rebuilt from transcript and restored.",
        ))
    # A8: a turn is already running — this write is steering, not a fresh turn.
    # Counted so the watchdog can warn if the CLI never picks it up (RC-7).
    if not active_session.turn_done.is_set():
        active_session.pending_prompts += 1
        logger.info(
            "Session '%s' message written mid-turn (queued_turns=%d)",
            name, active_session.pending_prompts,
        )
    active_session.turn_done.clear()  # a turn is starting — protect it from idle eviction
    active_session.turn_started_at = datetime.now()
    await active_session.out_queue.put(TurnState(session=name, running=True))
    active_session.proc.stdin.write(_encode_user_message(full_prompt, image_blocks))
    await active_session.proc.stdin.drain()
    return active_session.out_queue


def reset_idle(name: str) -> None:
    active = _sessions.get(name)
    if not active:
        return
    active.last_msg_at = datetime.now()
    active.idle_task.cancel()
    active.idle_task = asyncio.ensure_future(_idle_eviction(name))


def is_active(name: str) -> bool:
    """True when the session has a live subprocess/worker.

    A3 fix: Cursor sessions live entirely in session_manager_cursor's own
    registries, never in `_sessions` — so this used to always report False
    for Cursor regardless of real liveness.
    """
    if _session_agent(name) == "cursor":
        return session_manager_cursor.get_session_state(name) is not None
    return name in _sessions


def is_turn_running(name: str) -> bool:
    if session_manager_cursor.is_busy(name):
        return True
    active = _sessions.get(name)
    return active is not None and not active.turn_done.is_set()


def get_session_state(name: str) -> dict | None:
    """Snapshot of a live session's runtime state for watchdog diagnostics
    and GET /sessions (contract 2 liveness fields).

    Returns None when the session has no active subprocess.  Used by the
    Watchdog Medic to describe a stuck session without touching its process.

    last_user_msg_at vs last_output_at (A5/RC-9): these are deliberately
    separate clocks — the former is when the user's message was dispatched,
    the latter is when the process last actually produced stdout. Conflating
    them (the old "last_msg_at" field) made /medic and the sweeper measure
    "silence" from message-send time, so a genuinely stuck turn could still
    report silent_for_s≈0 if the user had just sent it.
    """
    if _session_agent(name) == "cursor":
        from devscope_bridge import session_manager_cursor
        return session_manager_cursor.get_session_state(name)
    active = _sessions.get(name)
    if active is None:
        return None
    turn_running = not active.turn_done.is_set()
    turn_elapsed_s = None
    if turn_running and active.turn_started_at is not None:
        turn_elapsed_s = (datetime.now() - active.turn_started_at).total_seconds()
    return {
        "name": active.name,
        "agent": "claude",
        "pid": active.proc.pid,
        "returncode": active.proc.returncode,
        "turn_done": active.turn_done.is_set(),
        "last_user_msg_at": active.last_msg_at.isoformat(),
        "last_output_at": session_reader.get_last_output_at(name),
        "current_tool": session_reader.get_current_tool(name),
        "turn_elapsed_s": turn_elapsed_s,
        "queued_turns": active.pending_prompts,
        "awaiting": session_reader.get_awaiting_kind(name),
        "mode": active.mode,
        "model": active.model,
        "out_queue": active.out_queue,
    }


async def kill_session(name: str) -> None:
    if _session_agent(name) == "cursor":
        session_manager_cursor.shutdown_cursor_session(name)
    await _terminate_session(name)


async def send_approval(
    name: str,
    request_id: str,
    option_id: str,
    *,
    answers: dict | None = None,
    custom_text: str | None = None,
) -> bool:
    """Forward permission / ask-user / tool-block responses to the active process.

    plan + approve → "yes proceed" user turn.
    ask_user + submit → formatted answers user turn.
    tool_blocked + allow_once → respawn with bypassPermissions + retry prompt.
    deny / skip → no-op (turn already ended).
    """
    from devscope_bridge import session_reader
    meta = session_reader._pending_permissions.pop(request_id, None)
    if meta is None:
        logger.warning(
            "send_approval: unknown request_id '%s' — already handled or expired",
            request_id,
        )
        kind = None
    else:
        kind = meta.get("kind")

    active = _sessions.get(name)
    if not active:
        logger.warning(
            "send_approval: no active session '%s' (request_id=%s)", name, request_id,
        )
        return False

    if option_id in ("deny", "skip"):
        logger.info(
            "Session '%s' permission denied/skipped (kind=%s, option_id=%s)",
            name, kind, option_id,
        )
        return True

    assert active.proc.stdin is not None

    if kind == "tool_blocked" and option_id in ("allow_once", "allow_always"):
        tool_name = (meta or {}).get("tool_name", "tool")
        tool_input = (meta or {}).get("tool_input") or {}
        stored = session_store.get_session(name)
        prior_session_id = stored["session_id"] if stored else None
        cwd = _session_cwd(name)
        if option_id == "allow_always":
            active.bypass_all_tools = True
        await _respawn_process(
            active, prior_session_id, cwd, active.mode, active.model,
            permission_mode_override="bypassPermissions",
        )
        retry_text = (
            f"The user approved running {tool_name}. "
            f"Execute it now with this exact input:\n"
            f"{json.dumps(tool_input, indent=2)}"
        )
        active.turn_done.clear()
        await active.out_queue.put(TurnState(session=name, running=True))
        active.proc.stdin.write(_encode_user_message(retry_text))
        await active.proc.stdin.drain()
        logger.info(
            "Session '%s' %s retry for %s (request_id=%s)",
            name, option_id, tool_name, request_id,
        )
        return True

    if kind == "ask_user" and option_id == "submit":
        lines = ["My answers to your questions:"]
        for header, value in (answers or {}).items():
            if isinstance(value, list):
                joined = ", ".join(str(v) for v in value)
                lines.append(f"- {header}: {joined}")
            else:
                lines.append(f"- {header}: {value}")
        if custom_text:
            lines.append(f"\nAdditional note: {custom_text}")
        approval_text = "\n".join(lines)
    elif kind == "plan" and option_id == "approve":
        approval_text = "yes proceed"
    elif option_id == "approve":
        approval_text = "yes proceed"
    else:
        logger.warning(
            "send_approval: unhandled kind=%s option_id=%s", kind, option_id,
        )
        return False

    active.turn_done.clear()
    await active.out_queue.put(TurnState(session=name, running=True))
    active.proc.stdin.write(_encode_user_message(approval_text))
    await active.proc.stdin.drain()
    logger.info(
        "Session '%s' approval sent (kind=%s, request_id=%s)",
        name, kind, request_id,
    )
    return True


def is_bypass_all_tools(name: str) -> bool:
    """True when the session has been granted permanent tool auto-approval."""
    active = _sessions.get(name)
    return bool(active and active.bypass_all_tools)


async def auto_approve_tool_blocked(
    name: str, tool_name: str, tool_input: dict
) -> None:
    """Called (fire-and-forget via ensure_future) when bypass_all_tools is set.

    Skips the UI card entirely. Only respawns when the live process is NOT already
    on --permission-mode bypassPermissions — repeated respawns used to flood the
    panel with fake ``[bridge] session terminated`` errors.
    """
    active = _sessions.get(name)
    if not active:
        return
    stored = session_store.get_session(name)
    prior_session_id = stored["session_id"] if stored else None
    cwd = _session_cwd(name)
    if not active.permission_bypass_active:
        await _respawn_process(
            active, prior_session_id, cwd, active.mode, active.model,
            permission_mode_override="bypassPermissions",
        )
    retry_text = (
        f"Permanent tool access granted. "
        f"Execute {tool_name} now with this exact input:\n"
        f"{json.dumps(tool_input, indent=2)}"
    )
    active.turn_done.clear()
    await active.out_queue.put(TurnState(session=name, running=True))
    assert active.proc.stdin is not None
    active.proc.stdin.write(_encode_user_message(retry_text))
    await active.proc.stdin.drain()
    logger.info("Session '%s' auto-approved %s (bypass_all_tools)", name, tool_name)


def interrupt_session(name: str) -> bool:
    """Send SIGINT (Claude) or kill cursor-agent (Cursor). False if nothing to stop."""
    if _session_agent(name) == "cursor":
        return session_manager_cursor.interrupt_cursor(name)

    active = _sessions.get(name)
    if not active:
        return False
    active.turn_done.clear()  # watchdog checks this to avoid redundant respawn
    try:
        os.kill(active.proc.pid, signal.SIGINT)
        logger.info("SIGINT sent to session '%s' (pid %d)", name, active.proc.pid)
    except ProcessLookupError:
        return False
    asyncio.ensure_future(_interrupt_watchdog(name, active.proc.pid))
    return True


async def _interrupt_watchdog(name: str, pid: int) -> None:
    """Force-respawn if the process doesn't emit a result within grace period.

    Like _watchdog_respawn, this clears the stored session_id before respawning
    so the new process starts fresh.  Resuming a SIGINT-killed session causes
    the new process to re-process the incomplete turn and hang.
    """
    await asyncio.sleep(_INTERRUPT_GRACE_S)
    active = _sessions.get(name)
    if active is None or active.proc.pid != pid:
        return  # cleaned up or already respawned
    if active.turn_done.is_set():
        return  # the interrupted turn ended naturally — no force respawn needed
    logger.warning(
        "Session '%s' (pid %d) did not respond to SIGINT in %ds — force respawning",
        name, pid, _INTERRUPT_GRACE_S,
    )
    preamble = build_recovery_preamble(name)
    session_store.clear_session_id(name)
    await active.out_queue.put(AiError(
        session=name, exit_code=-1,
        stderr_tail="[bridge] Turn interrupted: process hung after SIGINT — respawning",
    ))
    await _respawn_process(
        active, prior_session_id=None, cwd=_session_cwd(name),
        mode=active.mode, model=active.model,
    )
    active.pending_preamble = preamble
    active.turn_done.set()

