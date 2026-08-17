"""
session_manager.py — Manages persistent agent CLI subprocesses.

Supports two agents:
- "claude" : ONE persistent process per session using stream-json I/O.
  Messages are written to stdin; the process stays alive between turns.
  Turn completion is detected via the {"type":"result"} stream-json event.
- "cursor"  : blocking subprocess per call, delegated to session_manager_cursor.

Queue stability guarantee
-------------------------
The out_queue created on first spawn is NEVER replaced — it lives for the
WS session lifetime.  On respawn (mode/model change or dead process) the new
reader task is wired to the SAME queue so the pump in main.py stays valid.
"""

import asyncio
import json
import logging
import os
import signal
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from devscope_bridge import session_store
from devscope_bridge import session_manager_cursor
from devscope_bridge import session_reader
from devscope_bridge import sub_agent_tracker
from devscope_bridge.context_builder import build_context_preamble, extract_image_blocks
from devscope_bridge.models import (
    AgentActivity, AiDone, AiError, ContextRecovery, MessageContext, TurnState,
)
from devscope_bridge.mode_presets import MODE_PRESETS

logger = logging.getLogger(__name__)

DEFAULT_CWD = session_store.DEFAULT_CWD

_IDLE_TIMEOUT_S = 300
_KILL_GRACE_S = 5
_INTERRUPT_GRACE_S = 3   # SIGINT → force respawn if no result within this many seconds
# Safety net when the per-reader watchdog dies or is skipped (trickle/long_running).
_STALE_SWEEP_INTERVAL_S = 60.0
_STALE_TURN_ABS_S = 7200.0  # match session_reader._WATCHDOG_TURN_ABSOLUTE_CAP_S

_stale_sweeper_task: asyncio.Task | None = None

# Joins a compact/recovery preamble to the user's message. Without the explicit
# boundary the model reads the summary's "continue from here" and resumes the
# OLD task, ignoring the new message buried below a bare "---".
_PREAMBLE_USER_MSG_SEPARATOR = (
    "\n\n--- END OF BACKGROUND ---\n"
    "The message below is the user's CURRENT request — respond to it. "
    "Everything above is background context only; do not resume prior tasks "
    "unless the message below asks for that.\n\n"
)


@dataclass
class _ActiveSession:
    name: str
    session_id: str
    proc: asyncio.subprocess.Process
    out_queue: asyncio.Queue          # STABLE across respawns — never replaced
    reader_task: asyncio.Task
    idle_task: asyncio.Task
    mode: str | None                  # spawn-time mode (changing triggers respawn)
    model: str | None                 # spawn-time model (changing triggers respawn)
    claude_agent: str | None = None   # spawn-time --agent slug (changing triggers respawn)
    # Set by the reader on every turn end; cleared by interrupt_session so its
    # watchdog can tell whether the interrupted turn finished naturally.
    turn_done: asyncio.Event = field(default_factory=asyncio.Event)
    last_msg_at: datetime = field(default_factory=datetime.now)
    # Recovery preamble stashed at forced-respawn time (rebuilt from the OLD
    # transcript) — prepended to the NEXT user message so the fresh process
    # regains context it would otherwise have forgotten.  Cleared after use.
    pending_preamble: str | None = None
    # Set by /add-dir to force a respawn on the next message, so the new
    # subprocess is launched with the updated --add-dir flags.  Cleared by
    # _respawn_process once the respawn completes.
    pending_respawn: bool = False
    # Set by allow_always: all future tool-blocked events are auto-approved.
    bypass_all_tools: bool = False
    # True once the *subprocess* was spawned with --permission-mode bypassPermissions.
    # Used so subsequent tool_blocked events don't kill+respawn again (which was
    # wrongly showing red "Error (exit -1): [bridge] session terminated" mid-turn).
    permission_bypass_active: bool = False
    # A3: wall-clock start of the CURRENT turn (None while idle) — drives
    # turn_elapsed_s in get_session_state()/GET /sessions (contract 2).
    turn_started_at: datetime | None = None
    # A8: steering messages written to stdin while a turn was already running,
    # not yet picked up as a new turn by the CLI. Incremented in run_prompt,
    # decremented by session_reader.decrement_pending_prompts() when the next
    # turn's first stdout event arrives. Exposed as queued_turns.
    pending_prompts: int = 0
    # Messages that arrived mid-turn while Task/Agent sub-agents were in
    # flight — writing them to stdin would interrupt the CLI and kill the
    # sub-agents. Stored as already-composed (full_prompt, image_blocks)
    # tuples; flushed one per turn end by flush_deferred_message().
    deferred_messages: list[tuple[str, list[dict]]] = field(default_factory=list)
    # pid the deferred messages were queued against — a different pid at flush
    # time means the process died/respawned, so the queue is dropped.
    deferred_pid: int | None = None


_sessions: dict[str, _ActiveSession] = {}

# A1: persistent out_queue per session, allocated lazily and reused for the
# session's whole lifetime — INCLUDING the gap before the first message is
# ever sent. main.py's WS handler resolves this SAME queue to attach its pump
# on connect (not just on first user_msg); run_prompt's claude-spawn path
# below fetches from here too, so the pump is never bound to a throwaway
# queue that the real session ends up writing to a different object (RC-4).
_out_queues: dict[str, asyncio.Queue] = {}


def get_or_create_out_queue(name: str) -> asyncio.Queue:
    q = _out_queues.get(name)
    if q is None:
        q = asyncio.Queue()
        _out_queues[name] = q
    return q


def forget_out_queue(name: str) -> None:
    """Drop the out_queue registry entry — call only on full session deletion.

    NOT called by kill_session/reset (those intentionally keep the queue so a
    respawn or PTY handoff stays wired to the same already-attached WS pump).
    """
    _out_queues.pop(name, None)


def decrement_pending_prompts(name: str) -> None:
    """Called by session_reader when a new turn's first stdout event arrives."""
    active = _sessions.get(name)
    if active is not None and active.pending_prompts > 0:
        active.pending_prompts -= 1


async def _force_turn_idle(active: _ActiveSession, *, reason: str) -> None:
    """Unblock UI + /sessions turn_running even if the subprocess is wedged."""
    if not active.turn_done.is_set():
        active.turn_done.set()
    try:
        await active.out_queue.put(TurnState(session=active.name, running=False))
        await active.out_queue.put(AiError(
            session=active.name, exit_code=-1, stderr_tail=f"[bridge] {reason}",
        ))
    except Exception:  # noqa: BLE001
        logger.exception("Failed to emit idle frames for '%s'", active.name)


def _turn_silence_age_s(active: "_ActiveSession", now: datetime) -> float:
    """Seconds since real turn progress — last_output_at when known (A5/RC-9).

    Falls back to last_msg_at (time the message was dispatched) only when no
    stdout has arrived yet at all — e.g. the process just spawned and hasn't
    printed its first event. Using the dispatch time as "silence" here was the
    bug: a session that had been happily streaming for an hour still measured
    "silence" from the last message, not the last time it actually did anything.
    """
    last_output_at = session_reader.get_last_output_at(active.name)
    if last_output_at is not None:
        return max(0.0, time.time() - last_output_at)
    return (now - active.last_msg_at).total_seconds()


async def _stale_turn_sweeper() -> None:
    """Periodic scan: dead procs or turns older than absolute cap → force idle."""
    while True:
        await asyncio.sleep(_STALE_SWEEP_INTERVAL_S)
        now = datetime.now()
        for name, active in list(_sessions.items()):
            if active.turn_done.is_set():
                continue
            age_s = _turn_silence_age_s(active, now)
            dead = active.proc.returncode is not None
            if not dead and age_s < _STALE_TURN_ABS_S:
                continue
            why = (
                f"stale sweeper: process exited mid-turn (age {age_s:.0f}s)"
                if dead
                else f"stale sweeper: turn age {age_s:.0f}s exceeded absolute cap"
            )
            logger.warning("Session '%s' — %s", name, why)
            await _force_turn_idle(active, reason=why)
            if not dead:
                try:
                    os.kill(active.proc.pid, signal.SIGINT)
                except ProcessLookupError:
                    pass
                asyncio.ensure_future(_watchdog_respawn(name, active.proc.pid))


def start_stale_turn_sweeper() -> None:
    global _stale_sweeper_task
    if _stale_sweeper_task is not None and not _stale_sweeper_task.done():
        return
    _stale_sweeper_task = asyncio.create_task(_stale_turn_sweeper())
    logger.info(
        "stale-turn sweeper started (interval=%ss abs=%ss)",
        _STALE_SWEEP_INTERVAL_S, _STALE_TURN_ABS_S,
    )


async def stop_stale_turn_sweeper() -> None:
    global _stale_sweeper_task
    if _stale_sweeper_task is None:
        return
    _stale_sweeper_task.cancel()
    try:
        await _stale_sweeper_task
    except asyncio.CancelledError:
        pass
    _stale_sweeper_task = None


def _session_agent(name: str) -> str:
    meta = session_store.get_metadata(name)
    return meta["agent"] if meta else session_store.DEFAULT_AGENT


def _session_cwd(name: str) -> str:
    meta = session_store.get_metadata(name)
    return meta["cwd"] if meta else DEFAULT_CWD


def _session_mode(name: str) -> str | None:
    meta = session_store.get_metadata(name)
    return meta.get("mode") if meta else None


def _session_model(name: str) -> str | None:
    meta = session_store.get_metadata(name)
    return meta.get("model") if meta else None


def _session_claude_agent(name: str) -> str | None:
    meta = session_store.get_metadata(name)
    return meta.get("claude_agent") if meta else None

# Headless chat supports AskUserQuestion via PermissionRequest cards in the UI.
_INTERACTIVE_GUARD = (
    "When you need a structured choice from the user, use AskUserQuestion. "
    "For open-ended follow-ups, ask in plain text and end your turn."
)


def _build_claude_args(
    session_id: str | None,
    mode: str | None = None,
    model: str | None = None,
    *,
    permission_mode_override: str | None = None,
    extra_dirs: list[str] | None = None,
    claude_agent: str | None = None,
) -> list[str]:
    args = [
        "claude", "--print",
        "--input-format", "stream-json",
        "--output-format", "stream-json",
        "--include-partial-messages", "--verbose",
    ]
    if session_id:
        args += ["--resume", session_id]
    preset = MODE_PRESETS.get(mode or "act")
    if preset:
        claude_args = list(preset["claude_args"])
        if permission_mode_override:
            filtered: list[str] = []
            skip_next = False
            for arg in claude_args:
                if skip_next:
                    skip_next = False
                    continue
                if arg == "--permission-mode":
                    skip_next = True
                    continue
                filtered.append(arg)
            claude_args = filtered + ["--permission-mode", permission_mode_override]
        args += claude_args
        suffix = preset["system_prompt_suffix"]
        combined = f"{_INTERACTIVE_GUARD} {suffix}".strip() if suffix else _INTERACTIVE_GUARD
        args += ["--append-system-prompt", combined]
    elif permission_mode_override:
        args += ["--permission-mode", permission_mode_override]
        args += ["--append-system-prompt", _INTERACTIVE_GUARD]
    if model:
        args += ["--model", model]
    if claude_agent:
        args += ["--agent", claude_agent]
    for d in extra_dirs or []:
        args += ["--add-dir", d]
    # Global extra working dirs (e.g. sibling repos a worker may need to edit),
    # opt-in via DEVSCOPE_GLOBAL_ADD_DIRS (colon-separated absolute paths).
    _seen = set(extra_dirs or [])
    for d in os.environ.get("DEVSCOPE_GLOBAL_ADD_DIRS", "").split(":"):
        d = d.strip()
        if d and d not in _seen:
            args += ["--add-dir", d]
            _seen.add(d)
    return args


def subscription_env(session_name: str | None = None) -> dict[str, str]:
    """Env for the subprocess: forces OAuth billing, strips API keys.

    Opt into API-key billing with DEVSCOPE_USE_API_KEY=1.
    DEVSCOPE_SESSION tags the Claude MCP child so browser tools route to the
    correct DevScope session (and its bound browser tab).
    """
    env = dict(os.environ)
    if os.environ.get("DEVSCOPE_USE_API_KEY") != "1":
        env.pop("ANTHROPIC_API_KEY", None)
        env.pop("ANTHROPIC_AUTH_TOKEN", None)
    if session_name:
        env["DEVSCOPE_SESSION"] = session_name
    return env


# Strong references to in-flight drain tasks. asyncio only holds a weak
# reference to a task created via create_task — without keeping one
# ourselves, the task can be garbage-collected mid-run (a documented
# asyncio footgun). Entries are removed by the task's own done callback.
_drain_tasks: set[asyncio.Task] = set()


async def _drain_stderr(name: str, proc: asyncio.subprocess.Process) -> None:
    """Read the child's stderr forever so a chatty process can never block on a
    full pipe (the Cursor path already guards this; the Claude path did not).

    This is the SOLE consumer of proc.stderr — asyncio.StreamReader supports
    only one reader at a time, so continuous_reader's process-exit crash
    diagnostics no longer read proc.stderr directly (that raced with this
    loop). Instead they call session_reader.get_stderr_tail(name), which
    this loop feeds line-by-line as it drains.
    """
    if proc.stderr is None:
        return
    try:
        async for raw in proc.stderr:
            line = raw.decode("utf-8", "replace").rstrip()
            if line:
                logger.debug("[%s stderr] %s", name, line)
                session_reader.append_stderr_line(name, line)
    except Exception:
        pass


async def _spawn_claude_proc(
    prior_session_id: str | None,
    cwd: str,
    mode: str | None = None,
    model: str | None = None,
    *,
    permission_mode_override: str | None = None,
    session_name: str | None = None,
) -> asyncio.subprocess.Process:
    meta = session_store.get_metadata(session_name) if session_name else None
    extra_dirs: list[str] = (meta or {}).get("extra_dirs") or []
    args = _build_claude_args(
        prior_session_id, mode=mode, model=model,
        permission_mode_override=permission_mode_override,
        extra_dirs=extra_dirs,
        claude_agent=(meta or {}).get("claude_agent"),
    )
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        env=subscription_env(session_name),
    )
    drain_task = asyncio.create_task(_drain_stderr(session_name or "unknown", proc))
    _drain_tasks.add(drain_task)
    drain_task.add_done_callback(_drain_tasks.discard)
    return proc


def _encode_user_message(text: str, images: list[dict] | None = None) -> bytes:
    """Encode a user turn as a newline-delimited JSON stdin line for stream-json mode.

    `images` are Claude image content blocks (from extract_image_blocks). They
    are placed before the text block, which is what Anthropic recommends for
    best results when an image accompanies a prompt.
    """
    content: list[dict] = list(images or [])
    content.append({"type": "text", "text": text})
    payload = {
        "type": "user",
        "message": {"role": "user", "content": content},
    }
    return (json.dumps(payload) + "\n").encode("utf-8")


async def _notify_ui_session_end(active: _ActiveSession, reason: str) -> None:
    """Push a terminal frame so the side panel clears stale 'working' state."""
    if active.turn_done.is_set():
        await active.out_queue.put(AiDone(session=active.name))
    else:
        await active.out_queue.put(AiError(
            session=active.name,
            exit_code=-1,
            stderr_tail=f"[bridge] {reason}",
        ))


async def _terminate_process_only(
    active: _ActiveSession,
    *,
    reason: str = "session terminated",
    notify_ui: bool = True,
) -> None:
    """Kill the subprocess + cancel reader; leave out_queue and session entry intact.

    The reader is cancelled BEFORE the process is killed.  Otherwise the reader
    races to read the SIGTERM EOF and emits a misleading red "Error (exit 143)"
    for what is actually an intentional, graceful termination (idle eviction,
    respawn, or a terminal taking over the session).  _notify_ui_session_end has
    already pushed the correct terminal frame (AiDone when idle).

    Intentional mid-turn respawns (permission bypass) MUST pass notify_ui=False —
    otherwise the panel shows a fake fatal ``[bridge] session terminated`` error
    while work continues on the replacement process.
    """
    if notify_ui:
        await _notify_ui_session_end(active, reason)
    active.reader_task.cancel()
    try:
        active.proc.terminate()
        await asyncio.wait_for(active.proc.wait(), timeout=_KILL_GRACE_S)
    except (ProcessLookupError, asyncio.TimeoutError):
        try:
            active.proc.kill()
        except ProcessLookupError:
            pass


async def _terminate_session(name: str, *, reason: str = "session terminated") -> None:
    active = _sessions.pop(name, None)
    if not active:
        return
    await _terminate_process_only(active, reason=reason)
    active.idle_task.cancel()
    logger.info("Session '%s' terminated", name)


async def _idle_eviction(name: str) -> None:
    # Evict only when the session is genuinely IDLE (no turn running). A long
    # task keeps turn_done cleared, so it is never killed mid-turn — which used
    # to surface as exit 143 / "the agent stops on long tasks".
    while True:
        await asyncio.sleep(_IDLE_TIMEOUT_S)
        active = _sessions.get(name)
        if not active:
            return
        if not active.turn_done.is_set():
            continue  # a turn is in progress — keep the process alive
        if session_reader.get_pending_permissions(name):
            # Awaiting a user decision (permission / ask-user card). The turn
            # ended, but killing the process now orphans the approval — the
            # decision would land on "no active session" and the work is lost.
            continue
        logger.info("Session '%s' idle eviction", name)
        await _terminate_session(name, reason="Process idle-evicted after 5 min idle")
        return


def _needs_respawn(active: _ActiveSession, mode: str | None, model: str | None,
                   claude_agent: str | None = None) -> bool:
    return (
        active.proc.returncode is not None
        or active.mode != mode
        or active.model != model
        or active.claude_agent != claude_agent
        or active.pending_respawn
    )


def _message_text(entry: dict) -> str:
    """Extract plain text from a transcript message entry (string or block list)."""
    content = entry.get("message", {}).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
        return " ".join(p for p in parts if p)
    return ""


_SHORT_CONTINUATION_MAX = 80


def _cursor_needs_recovery_preamble(prompt: str, prior_session_id: str | None) -> bool:
    """Inject bridge transcript summary when Cursor may lack thread context."""
    if not prior_session_id:
        return True
    return len(prompt.strip()) <= _SHORT_CONTINUATION_MAX


def build_recovery_preamble(name: str) -> str | None:
    """Rebuild a compact context summary from stored transcript turns.

    Used after a forced respawn (no --resume) or for Cursor when chatId is missing.
    Returns None when there is no transcript or nothing extractable.
    """
    turns = session_store.read_transcript_turns(name, limit=24)
    if not turns:
        return None

    recent_users = [t["text"] for t in turns if t["role"] == "user"][-3:]
    recent_assistants = [t["text"] for t in turns if t["role"] == "assistant"][-2:]
    if not recent_users and not recent_assistants:
        return None

    lines = [
        "[Bridge context recovery] The agent process restarted without in-memory history.",
        "Continue the SAME thread — do not ask what task the user meant unless truly ambiguous.",
        "",
        "Recent user messages:",
    ]
    for text in recent_users:
        lines.append(f"- {text[:500]}")
    lines.append("")
    lines.append("Recent assistant progress:")
    for text in recent_assistants:
        lines.append(f"- {text[:800]}")
    lines.append("")
    lines.append(
        "Short replies like \"done\", \"בוצע\", or \"try now\" refer to the ongoing work above."
    )
    return "\n".join(lines)


async def _watchdog_respawn(name: str, pid: int) -> None:
    """Respawn after hard-cap SIGINT — no second AiError (watchdog already emitted one).

    After a hard-cap kill the interrupted conversation is in a broken state: it has
    a user turn with no assistant result.  Resuming with --resume <session_id> causes
    the new claude process to attempt to complete the interrupted turn, producing no
    response to the next user message (the "stuck after respawn" bug).

    Fix: respawn WITHOUT --resume so the new process starts a fresh conversation and
    reliably answers the next user message.  The session_store entry is cleared so
    run_prompt also does not accidentally pass the stale session_id.

    turn_done may already be set (UI unblocked immediately on hard-cap).  Still
    respawn if the same pid is alive so the next message is not stuck on a
    hung stdin pipe.
    """
    await asyncio.sleep(_INTERRUPT_GRACE_S)
    active = _sessions.get(name)
    if active is None or active.proc.pid != pid:
        return
    if active.proc.returncode is not None:
        # Process already gone — ensure idle bookkeeping only.
        if not active.turn_done.is_set():
            active.turn_done.set()
            await active.out_queue.put(TurnState(session=name, running=False))
        return
    logger.warning(
        "Session '%s' (pid %d) did not exit after SIGINT in %ds — respawning",
        name, pid, _INTERRUPT_GRACE_S,
    )
    # Rebuild a context summary from the OLD transcript BEFORE clearing the id —
    # the fresh process starts without --resume (which would replay the stuck
    # turn and hang), so we inject this summary into its next message instead.
    preamble = build_recovery_preamble(name)
    # Clear the stored session_id: resuming a SIGINT-killed session causes the new
    # process to hang re-processing the incomplete turn.  Start fresh instead.
    session_store.clear_session_id(name)
    await _respawn_process(
        active, prior_session_id=None, cwd=_session_cwd(name),
        mode=active.mode, model=active.model,
    )
    active.pending_preamble = preamble
    # The interrupted turn is over — set turn_done so idle-eviction bookkeeping is
    # consistent and so _interrupt_watchdog / _watchdog_respawn don't double-fire.
    active.turn_done.set()
    await active.out_queue.put(TurnState(session=name, running=False))


def _make_hard_interrupt_fn(name: str) -> Callable[[], None]:
    """Return the callable the watchdog invokes at hard-cap to SIGINT + respawn.

    AiError is emitted by the watchdog before this is called — this only
    sends SIGINT and schedules a respawn, never a second AiError.
    Marks turn idle immediately so /sessions + UI unblock even if respawn hangs.
    """
    def _interrupt_fn() -> None:
        active = _sessions.get(name)
        if active is None:
            return
        pid = active.proc.pid
        # Unblock UI / queue NOW — do not wait for respawn grace.
        if not active.turn_done.is_set():
            active.turn_done.set()
            asyncio.ensure_future(active.out_queue.put(
                TurnState(session=name, running=False),
            ))
        try:
            os.kill(pid, signal.SIGINT)
            logger.info("Watchdog hard-cap: SIGINT → '%s' (pid %d)", name, pid)
        except ProcessLookupError:
            pass
        asyncio.ensure_future(_watchdog_respawn(name, pid))
    return _interrupt_fn


def _make_pending_prompts_fn(name: str) -> Callable[[], int]:
    """Closure the watchdog polls to detect an unpicked-up steering message (A8)."""
    def _fn() -> int:
        active = _sessions.get(name)
        return active.pending_prompts if active is not None else 0
    return _fn


async def _respawn_process(
    active: _ActiveSession,
    prior_session_id: str | None,
    cwd: str,
    mode: str | None,
    model: str | None,
    *,
    permission_mode_override: str | None = None,
    claude_agent: str | None = None,
) -> None:
    """Terminate old subprocess, spawn new one, rewire reader to the SAME queue."""
    logger.info(
        "Session '%s' respawning (mode=%s→%s model=%s→%s agent=%s→%s bypass=%s)",
        active.name, active.mode, mode, active.model, model,
        active.claude_agent, claude_agent, permission_mode_override,
    )
    # Quiet kill — UI must not see AiError("session terminated") for a planned respawn.
    await _terminate_process_only(active, notify_ui=False)
    new_proc = await _spawn_claude_proc(
        prior_session_id, cwd, mode=mode, model=model,
        permission_mode_override=permission_mode_override,
        session_name=active.name,
    )
    active.proc = new_proc
    active.mode = mode
    active.model = model
    active.claude_agent = claude_agent
    active.pending_respawn = False
    if permission_mode_override == "bypassPermissions":
        active.permission_bypass_active = True
        active.bypass_all_tools = True
    elif not permission_mode_override:
        # Mode/model respawn without override — subprocess no longer has bypassPermissions.
        active.permission_bypass_active = False
    active.reader_task = asyncio.create_task(
        session_reader.continuous_reader(
            active.name, new_proc, active.out_queue, active.turn_done,
            hard_interrupt_fn=_make_hard_interrupt_fn(active.name),
            pending_prompts_fn=_make_pending_prompts_fn(active.name),
        )
    )
    logger.info("Session '%s' respawned (pid %d)", active.name, new_proc.pid)


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
