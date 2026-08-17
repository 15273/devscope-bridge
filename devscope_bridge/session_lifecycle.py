"""Spawn, terminate, respawn, and stale-turn sweeper for Claude sessions."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from collections.abc import Callable
from datetime import datetime

from devscope_bridge import session_reader
from devscope_bridge import session_store
from devscope_bridge.models import AiDone, AiError, TurnState
from devscope_bridge.mode_presets import MODE_PRESETS
from devscope_bridge.session_recovery import build_recovery_preamble
from devscope_bridge.session_runtime import (
    _ActiveSession,
    _IDLE_TIMEOUT_S,
    _INTERRUPT_GRACE_S,
    _KILL_GRACE_S,
    _STALE_SWEEP_INTERVAL_S,
    _STALE_TURN_ABS_S,
    _session_cwd,
    _sessions,
    subscription_env,
)

logger = logging.getLogger(__name__)

_stale_sweeper_task: asyncio.Task | None = None

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
    from devscope_bridge import session_manager as _sm
    proc = await _sm.asyncio.create_subprocess_exec(
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
    from devscope_bridge import session_manager as _sm
    await asyncio.sleep(_sm._INTERRUPT_GRACE_S)
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

