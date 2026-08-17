"""Async watchdog for cursor-agent turns — same tiers as Claude session_reader."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable

from devscope_bridge.models import AgentActivity
from devscope_bridge import session_reader as sr

logger = logging.getLogger(__name__)

_turn_started: dict[str, float] = {}
_last_stdout: dict[str, float] = {}
_kill_reason: dict[str, str] = {}

# Wall-clock (epoch) mirrors of the monotonic clocks above, plus current-tool
# tracking — exposed via get_session_state() per cross-workstream contract 2
# (last_output_at, turn_elapsed_s, current_tool). Monotonic clocks above stay
# authoritative for internal silence/elapsed math; these are for external
# consumers (medic, /sessions) that want an epoch timestamp or a live value.
_last_stdout_epoch: dict[str, float] = {}
_current_tool: dict[str, str | None] = {}


def begin_turn(session: str) -> None:
    now = time.monotonic()
    _turn_started[session] = now
    _last_stdout[session] = now
    _last_stdout_epoch[session] = time.time()
    _current_tool.pop(session, None)


def end_turn(session: str) -> None:
    _turn_started.pop(session, None)
    _last_stdout.pop(session, None)
    _last_stdout_epoch.pop(session, None)
    _current_tool.pop(session, None)
    _kill_reason.pop(session, None)


def touch_stdout(session: str) -> None:
    _last_stdout[session] = time.monotonic()
    _last_stdout_epoch[session] = time.time()


def consume_kill_reason(session: str) -> str | None:
    return _kill_reason.pop(session, None)


def set_current_tool(session: str, tool: str | None) -> None:
    """Track the tool currently in flight for this session (None = idle)."""
    if tool is None:
        _current_tool.pop(session, None)
    else:
        _current_tool[session] = tool


def get_current_tool(session: str) -> str | None:
    return _current_tool.get(session)


def get_last_output_epoch(session: str) -> float | None:
    """Epoch-seconds timestamp of the last stdout activity (contract-2 last_output_at)."""
    return _last_stdout_epoch.get(session)


def get_turn_elapsed_s(session: str) -> float | None:
    """Seconds since the current turn started, or None if no turn is running."""
    started = _turn_started.get(session)
    if started is None:
        return None
    return time.monotonic() - started


async def run(
    session: str,
    out_q: asyncio.Queue,
    *,
    is_running: Callable[[], bool],
    kill_proc: Callable[[], None],
    medic_active: asyncio.Event,
) -> None:
    """Heartbeat → medic → hard-kill when cursor-agent stdout goes silent."""
    tick = min(10.0, max(0.05, sr._WATCHDOG_HEARTBEAT_S / 2))
    heartbeat_emitted = False
    medic_triggered = False
    hard_cap_triggered = False
    medic_defer_elapsed = 0.0

    while is_running():
        await asyncio.sleep(tick)
        if not is_running():
            break

        now = time.monotonic()
        started = _turn_started.get(session, now)
        last_out = _last_stdout.get(session, started)
        silence = now - last_out
        turn_elapsed = now - started

        if silence >= sr._WATCHDOG_HEARTBEAT_S and not heartbeat_emitted:
            heartbeat_emitted = True
            await out_q.put(AgentActivity(
                session=session,
                label="still working…",
                detail=f"No cursor output for {silence:.0f}s (turn {turn_elapsed:.0f}s)",
            ))

        medic_due = (
            silence >= sr._WATCHDOG_MEDIC_S
            or turn_elapsed >= sr._WATCHDOG_TURN_WALL_MEDIC_S
        )
        if medic_due and not medic_triggered:
            medic_triggered = True
            trigger_elapsed = max(silence, turn_elapsed)
            logger.warning(
                "Cursor session '%s' medic trigger (silent %.0fs, turn %.0fs)",
                session, silence, turn_elapsed,
            )
            from devscope_bridge import watchdog_medic
            asyncio.ensure_future(
                watchdog_medic.run_medic(session, out_q, medic_active, trigger_elapsed),
            )

        silence_due = silence >= sr._WATCHDOG_HARD_CAP_S
        wall_due = turn_elapsed >= sr._WATCHDOG_TURN_WALL_CAP_S
        absolute_due = turn_elapsed >= sr._WATCHDOG_TURN_ABSOLUTE_CAP_S
        hard_due = silence_due or wall_due or absolute_due
        if hard_due and not hard_cap_triggered:
            if (
                medic_active.is_set()
                and not absolute_due
                and medic_defer_elapsed < sr._WATCHDOG_MEDIC_DEFER_MAX_S
            ):
                medic_defer_elapsed += tick
                continue
            hard_cap_triggered = True
            if absolute_due:
                reason = (
                    f"[bridge] cursor-agent turn exceeded absolute "
                    f"{turn_elapsed:.0f}s — turn stopped"
                )
            elif wall_due:
                reason = f"[bridge] cursor-agent turn exceeded {turn_elapsed:.0f}s — turn stopped"
            else:
                reason = f"[bridge] cursor-agent silent for {silence:.0f}s — turn stopped"
            _kill_reason[session] = reason
            logger.warning("Cursor session '%s' hard cap — killing subprocess", session)
            kill_proc()
