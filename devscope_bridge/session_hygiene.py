"""
session_hygiene.py — Automatic token-burn prevention for orchestrator sessions.

Managers (mom, mgr-*) reuse the same DevScope session every tick; without reset
each turn re-reads the entire conversation as cache. Workers accumulate in
sessions.json after tasks finish. Recovery pipelines can flood the task DB.

This module runs proactively (background loop + hooks in orchestrator) so the
user does not need to manually /new or pause.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from pathlib import Path

from devscope_bridge import oauth_usage_service, session_manager, session_reader, session_store, task_store
from devscope_bridge.orchestrator_config import OrchestratorSettings, load as load_settings, save as save_settings

logger = logging.getLogger(__name__)

TASKS_DB = Path.home() / ".dev-bridge" / "agent_tasks.db"
_ORCHESTRATOR_NAMES = frozenset({"mom"})
_MGR_PREFIX = "mgr-"
_WORKER_PREFIX = "worker-"
_LOOP_INTERVAL_S = 300.0


_AUTOMATION_PURPOSES = frozenset({"orchestrator", "manager", "worker"})
_SCHED_SETUP_PREFIX = "sched-setup-"


def session_purpose(name: str, entry: dict | None = None) -> str:
    """Resolve DevScope session purpose (name heuristic overrides generic metadata)."""
    if name == "mom":
        return "orchestrator"
    if name.startswith(_MGR_PREFIX):
        return "manager"
    if name.startswith(_WORKER_PREFIX):
        return "worker"
    if name.startswith(_SCHED_SETUP_PREFIX):
        return "schedule_setup"
    meta = entry if entry is not None else session_store.get_session(name)
    if meta and meta.get("purpose"):
        return str(meta["purpose"])
    return "chat"


def is_automation_session(name: str, entry: dict | None = None) -> bool:
    return session_purpose(name, entry) in _AUTOMATION_PURPOSES


def _is_orchestrator_session(name: str) -> bool:
    return name == "mom" or name.startswith(_MGR_PREFIX)


def _queued_count() -> int:
    if not TASKS_DB.is_file():
        return 0
    conn = sqlite3.connect(TASKS_DB)
    try:
        row = conn.execute(
            """
            SELECT COUNT(*) FROM tasks
            WHERE status IN ('new', 'assigned', 'ready', 'approved')
            """
        ).fetchone()
        return int(row[0]) if row else 0
    finally:
        conn.close()


async def reset_for_fresh_turn(session_name: str) -> bool:
    """Drop resume id (Claude session_id / Cursor chatId) for a clean next turn."""
    if session_manager.is_turn_running(session_name):
        logger.debug("hygiene: skip reset — turn running on %s", session_name)
        return False
    entry = session_store.get_session(session_name)
    if entry is None:
        return False
    if not entry.get("session_id"):
        return False
    session_store.clear_session_id(session_name)
    await session_manager.kill_session(session_name)
    session_reader.reset_session_usage(session_name)
    logger.info("hygiene: reset session %s for fresh turn", session_name)
    return True


async def ensure_fresh_orchestrator_session(session_name: str) -> None:
    """Always reset mom/mgr-* before an orchestrator turn (state lives in DB)."""
    if not _is_orchestrator_session(session_name):
        return
    await reset_for_fresh_turn(session_name)


async def cleanup_worker_session(session_name: str, task_id: str) -> None:
    """After a worker finishes, drop resume id and prune metadata if terminal."""
    await reset_for_fresh_turn(session_name)
    row = task_store.get_task(task_id)
    if row and row["status"] == "in_progress":
        return
    if session_store.delete_session(session_name):
        logger.info("hygiene: pruned worker session %s", session_name)


def trim_recovery_backlog(cap: int = 50) -> int:
    """Cancel oldest ats_recovery tasks in ready/assigned beyond cap."""
    if cap <= 0:
        return 0
    tasks = task_store.list_tasks()
    recovery = [
        t for t in tasks
        if t.get("source") == "ats_recovery" and t["status"] in ("ready", "assigned")
    ]
    if len(recovery) <= cap:
        return 0
    recovery.sort(key=lambda t: t.get("created_at") or "")
    cancelled = 0
    for task in recovery[: len(recovery) - cap]:
        task_store.update_task(
            task["id"],
            status="cancelled",
            result_summary="auto-cancelled: ATS recovery backlog cap",
        )
        task_store.add_log(task["id"], actor="hygiene", message="recovery backlog trim")
        cancelled += 1
    if cancelled:
        logger.warning("hygiene: cancelled %d excess ats_recovery tasks (cap=%d)", cancelled, cap)
    return cancelled


def prune_worker_sessions(max_sessions: int = 80) -> int:
    """Remove idle worker-* entries from sessions.json beyond max_sessions."""
    if max_sessions <= 0:
        return 0
    sessions = session_store.load_sessions()
    workers = [(n, sessions[n]) for n in sessions if n.startswith(_WORKER_PREFIX)]
    if len(workers) <= max_sessions:
        return 0
    workers.sort(key=lambda x: x[1].get("last_used") or "", reverse=True)
    pruned = 0
    for name, _meta in workers[max_sessions:]:
        tid = name[len(_WORKER_PREFIX):]
        row = task_store.get_task(tid)
        if row and row["status"] == "in_progress":
            continue
        if session_store.delete_session(name):
            pruned += 1
    if pruned:
        logger.warning("hygiene: pruned %d stale worker sessions (cap=%d)", pruned, max_sessions)
    return pruned


def prune_schedule_setup_sessions() -> int:
    """Remove sched-setup-* metadata when the draft is completed or missing."""
    sessions = session_store.load_sessions()
    pruned = 0
    for name in list(sessions):
        if not name.startswith(_SCHED_SETUP_PREFIX):
            continue
        draft_id = name[len(_SCHED_SETUP_PREFIX):]
        try:
            from devscope_bridge import schedule_setup
            draft = schedule_setup.get_draft(draft_id)
        except Exception:
            draft = None
        if draft is None or draft.get("status") == "completed":
            if session_store.delete_session(name):
                pruned += 1
    if pruned:
        logger.info("hygiene: pruned %d completed schedule-setup sessions", pruned)
    return pruned


async def reset_stale_automation_sessions() -> int:
    """Reset idle automation sessions (Claude + Cursor) that still hold a resume id."""
    sessions = session_store.load_sessions()
    reset = 0
    for name, meta in sessions.items():
        if not is_automation_session(name, meta):
            continue
        if await reset_for_fresh_turn(name):
            reset += 1
    return reset


async def reset_stale_orchestrator_sessions() -> int:
    """Backward-compatible alias."""
    return await reset_stale_automation_sessions()


async def maybe_auto_pause(settings: OrchestratorSettings) -> bool:
    """Pause orchestrator when quota is high and backlog is large."""
    if settings.paused or not settings.auto_hygiene_enabled:
        return False
    if settings.auto_pause_utilization <= 0:
        return False
    usage = await oauth_usage_service.get_usage()
    if not usage.get("available"):
        return False
    bucket = (usage.get("limits") or {}).get("five_hour") or {}
    util = bucket.get("utilization")
    if util is None:
        return False
    util_pct = float(util)
    queued = _queued_count()
    if util_pct < settings.auto_pause_utilization or queued < settings.auto_pause_min_queued:
        return False
    settings.paused = True
    save_settings(settings)
    logger.warning(
        "hygiene: auto-paused orchestrator (quota %.0f%%, queued=%d)",
        util_pct, queued,
    )
    return True


async def run_hygiene_pass(settings: OrchestratorSettings | None = None) -> dict:
    """One full hygiene cycle — safe to call from loop or orchestrator tick."""
    settings = settings or load_settings()
    if not settings.auto_hygiene_enabled:
        return {"skipped": True}

    stats = {
        "recovery_cancelled": trim_recovery_backlog(settings.recovery_backlog_cap),
        "workers_pruned": prune_worker_sessions(settings.worker_session_cap),
        "schedule_setups_pruned": prune_schedule_setup_sessions(),
        "automation_resets": await reset_stale_automation_sessions(),
        "auto_paused": await maybe_auto_pause(settings),
    }
    return stats


_bg_task: asyncio.Task | None = None


async def _background_loop() -> None:
    while True:
        try:
            stats = await run_hygiene_pass()
            if any(stats.get(k) for k in (
                "recovery_cancelled", "workers_pruned", "schedule_setups_pruned",
                "automation_resets", "auto_paused",
            )):
                logger.info("hygiene pass: %s", stats)
        except Exception:
            logger.exception("hygiene background pass failed")
        interval = max(60, load_settings().hygiene_interval_seconds)
        await asyncio.sleep(interval)


def start_background_loop() -> None:
    global _bg_task
    if _bg_task and not _bg_task.done():
        return
    _bg_task = asyncio.create_task(_background_loop())
    logger.info("session hygiene background loop started")


async def stop_background_loop() -> None:
    global _bg_task
    if _bg_task:
        _bg_task.cancel()
        try:
            await _bg_task
        except asyncio.CancelledError:
            pass
        _bg_task = None
