"""
session_runner.py — Thin layer the orchestrator uses to wake a Claude session
and wait for its turn to finish, without consuming the session's WS out_queue.
"""

import asyncio
import logging
from typing import Protocol

from devscope_bridge import session_manager, session_store

logger = logging.getLogger(__name__)

DEFAULT_CWD = session_store.DEFAULT_CWD
_TURN_START_GRACE_S = 2.0
_POLL_INTERVAL_S = 1.0


def _purpose_for_session(name: str) -> str:
    if name.startswith("worker-"):
        return "worker"
    if name.startswith("mgr-"):
        return "manager"
    if name == "mom":
        return "orchestrator"
    return "chat"


class SessionRunner(Protocol):
    async def run_turn(self, name: str, prompt: str, *, mode: str = "act",
                       agent: str = "claude", timeout_s: float = 600.0,
                       cwd: str | None = None) -> bool: ...


class BridgeSessionRunner:
    """Real runner backed by session_manager. One instance per orchestrator."""

    async def run_turn(self, name: str, prompt: str, *, mode: str = "act",
                       agent: str = "claude", timeout_s: float = 600.0,
                       cwd: str | None = None) -> bool:
        """Ensure the session exists, send the prompt, await turn completion.

        Returns True if the turn completed within timeout, False on timeout.
        ``cwd`` pins a fresh session to a project directory (per-task
        project_path); existing sessions keep their stored cwd.
        """
        if agent not in ("claude", "cursor"):
            agent = "claude"
        if session_store.get_session(name) is None:
            session_store.create_session_metadata(
                name=name,
                agent=agent,
                cwd=cwd or DEFAULT_CWD,
                mode=mode,
                purpose=_purpose_for_session(name),
            )
        await session_manager.run_prompt(name, prompt, mode=mode)
        return await self._await_turn(name, timeout_s)

    async def _await_turn(self, name: str, timeout_s: float) -> bool:
        await asyncio.sleep(_TURN_START_GRACE_S)  # let turn_done clear
        waited = _TURN_START_GRACE_S
        while session_manager.is_turn_running(name):
            if waited >= timeout_s:
                logger.warning("orchestrator: turn timeout for session '%s'", name)
                return False
            await asyncio.sleep(_POLL_INTERVAL_S)
            waited += _POLL_INTERVAL_S
        self._drain_idle_queue(name)
        return True

    @staticmethod
    def _drain_idle_queue(name: str) -> None:
        """Bounded best-effort drain so a panel-less session's queue stays small.

        If a WS pump is attached it has already consumed the frames and this is a
        no-op; if not, this clears the backlog. Never blocks.
        """
        state = session_manager.get_session_state(name)
        q = state.get("out_queue") if state else None
        if q is None:
            return
        for _ in range(1000):
            try:
                q.get_nowait()
            except asyncio.QueueEmpty:
                break
