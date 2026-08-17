"""Live session registry, queues, and metadata helpers.

Shared by session_lifecycle and session_manager.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime

from devscope_bridge import session_store

logger = logging.getLogger(__name__)

DEFAULT_CWD = session_store.DEFAULT_CWD

_IDLE_TIMEOUT_S = 300
_KILL_GRACE_S = 5
_INTERRUPT_GRACE_S = 3   # SIGINT → force respawn if no result within this many seconds
# Safety net when the per-reader watchdog dies or is skipped (trickle/long_running).
_STALE_SWEEP_INTERVAL_S = 60.0
_STALE_TURN_ABS_S = 7200.0  # match session_reader._WATCHDOG_TURN_ABSOLUTE_CAP_S


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
