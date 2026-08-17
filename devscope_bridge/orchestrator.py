"""
orchestrator.py — The 5-step tick loop that drives the 3-tier Claude hierarchy.

Python owns the heartbeat, concurrency cap, and dispatch; Claude (woken via the
SessionRunner) owns triage and execution. The decision logic lives in
orchestrator_core; this module is the glue + the asyncio loop.
"""

import asyncio
import logging
from datetime import datetime

from devscope_bridge import agent_policies, board_relay, board_state, orchestrator_core as oc, task_store
from devscope_bridge import employee_config, external_board
from devscope_bridge import orchestrator_config, orchestrator_throttle, session_hygiene
from devscope_bridge.orchestrator_config import OrchestratorConfig
from devscope_bridge.session_reader import mark_long_running, clear_long_running

logger = logging.getLogger(__name__)

MOM_SESSION = "mom"
WORKER_TIMEOUT_S = 1800.0   # workers run long browser tasks
_STALE_WORKER_MINUTES = 10  # in_progress + idle session → auto-fail
_STALE_PARENT_MINUTES = 180  # parent in_progress, no live children, idle → auto-fail
_TS_FMT = "%Y-%m-%d %H:%M:%S"


def reconcile_stuck_workers(now: str | None = None, *, stale_minutes: int = _STALE_WORKER_MINUTES) -> int:
    """Fail worker_units stuck in in_progress while their assignee session is idle.

    Workers are supposed to call task_update when finished; if a turn ends (or
    never starts) without that, the slot stays occupied and blocks dispatch.
    """
    from devscope_bridge import session_manager

    now_dt = datetime.strptime(now or datetime.now().strftime(_TS_FMT), _TS_FMT)
    cleared = 0
    for task in task_store.list_tasks(status="in_progress"):
        if task.get("kind") != "worker_unit":
            continue
        name = task.get("assignee_session") or f"worker-{task['id']}"
        if session_manager.is_turn_running(name):
            continue
        try:
            updated = datetime.strptime(task["updated_at"], _TS_FMT)
        except (KeyError, ValueError):
            updated = now_dt
        age_min = (now_dt - updated).total_seconds() / 60.0
        if age_min < stale_minutes:
            continue
        task_store.update_task(
            task["id"],
            status="failed",
            result_summary=(
                "Worker ended without marking task done "
                f"(auto-reconciled after {int(age_min)}m idle)"
            ),
        )
        task_store.add_log(
            task["id"], actor="orchestrator",
            message=f"reconciled stale in_progress ({name})",
        )
        cleared += 1
    if cleared:
        logger.warning("reconciled %d stuck worker(s)", cleared)
    return cleared


def reconcile_stuck_parents(now: str | None = None, *,
                            stale_minutes: int = _STALE_PARENT_MINUTES) -> int:
    """Fail in-progress parent tasks (mom_task/domain_task) idle longer than
    stale_minutes that have NO non-terminal children.

    Worker capacity is already protected (running_worker_count counts only
    worker_units), but a parent that never gets closed otherwise lingers
    in_progress forever — this is the backstop that previously required a manual
    cleanup. A parent with any ready/in_progress/assigned/new child is left alone
    (still doing real work); one whose children are all terminal (or has none)
    and is idle is a zombie and gets failed.
    """
    now_dt = datetime.strptime(now or datetime.now().strftime(_TS_FMT), _TS_FMT)
    cleared = 0
    for task in task_store.list_tasks(status="in_progress"):
        if task.get("kind") == "worker_unit":
            continue
        children = task_store.list_tasks(parent_id=task["id"])
        if any(c["status"] not in oc._TERMINAL_STATUSES for c in children):
            continue  # still has live children — real work in flight
        try:
            updated = datetime.strptime(task["updated_at"], _TS_FMT)
        except (KeyError, ValueError):
            updated = now_dt
        if (now_dt - updated).total_seconds() / 60.0 < stale_minutes:
            continue
        task_store.update_task(
            task["id"], status="failed",
            result_summary=f"Parent auto-reconciled (idle >{stale_minutes}m, no live children)",
        )
        task_store.add_log(task["id"], actor="orchestrator",
                           message="reconciled stuck parent")
        cleared += 1
    if cleared:
        logger.warning("reconciled %d stuck parent(s)", cleared)
    return cleared


def _digest(tasks: list[dict]) -> str:
    if not tasks:
        return "(none)"
    return "\n".join(f"- [{t['id']}] ({t['status']}) {t['title']}"
                     f"{' — ' + t['instruction'] if t.get('instruction') else ''}"
                     for t in tasks)


def _rollup_digest(parents: list[dict]) -> str:
    """List each parent ready for closure with its finished worker_units' results."""
    lines = []
    for p in parents:
        lines.append(f"- parent [{p['id']}] {p['title']}")
        for c in task_store.list_tasks(parent_id=p["id"]):
            if c.get("kind") != "worker_unit":
                continue
            lines.append(f"    • unit [{c['id']}] {c['status']}: "
                         f"{c.get('result_summary') or '(no summary)'}")
    return "\n".join(lines)


def _project_tree_digest(project: dict) -> str:
    """Milestones + their unit results, for the MoM project-review turn."""
    lines = [f"- root [{project['id']}] {project['title']}"]
    for m in task_store.list_tasks(parent_id=project["id"]):
        lines.append(f"  • milestone [{m['id']}] {m['status']}: {m['title']} — "
                     f"{m.get('result_summary') or '(no summary)'}")
        for u in task_store.list_tasks(parent_id=m["id"]):
            lines.append(f"      · unit [{u['id']}] {u['status']}: "
                         f"{u.get('result_summary') or '(no summary)'}")
    return "\n".join(lines)


async def run_tick(
    runner,
    cfg: OrchestratorConfig,
    now: str | None = None,
    *,
    throttle_info: dict | None = None,
) -> None:
    """One orchestrator cycle: collect → MoM → domains → dispatch → board digest."""
    board_state.mark_tick_start(cfg.tick_seconds)
    settings = orchestrator_config.load()
    if settings.auto_hygiene_enabled:
        await session_hygiene.run_hygiene_pass(settings)
    reconcile_stuck_workers(now=now)
    reconcile_stuck_parents(now=now)
    # 1. Collect + materialise schedules; requeue approval-granted workers
    oc.materialise_due_schedules(now=now)
    b = oc.collect()
    if oc.requeue_approved_workers(b):
        b = oc.collect()

    # 2. MoM triage (skip if no new top-level work)
    if oc.should_wake_mom(b):
        await session_hygiene.ensure_fresh_orchestrator_session(MOM_SESSION)
        await runner.run_turn(MOM_SESSION,
                              agent_policies.build_mom_prompt(_digest(b.new_tasks)))
        b = oc.collect()  # MoM may have produced assigned tasks

    # 3. Domain managers — break down new assigned work AND close finished parents
    rollup_by_domain: dict[str, list[dict]] = {}
    for parent in oc.parents_ready_for_rollup(b, cfg.domains):
        rollup_by_domain.setdefault(parent["domain"], []).append(parent)
    active = set(oc.domains_needing_triage(b, cfg.domains)) | set(rollup_by_domain)
    for domain in sorted(active):
        assigned = [t for t in b.assigned_tasks if t["domain"] == domain]
        mgr_name = f"mgr-{domain}"
        await session_hygiene.ensure_fresh_orchestrator_session(mgr_name)
        await runner.run_turn(mgr_name,
                              agent_policies.build_domain_prompt(
                                  domain, _digest(assigned),
                                  _rollup_digest(rollup_by_domain.get(domain, []))))
    b = oc.collect()  # domain managers may have produced ready workers / closed parents

    # 3.5 Project review — MoM synthesises and closes finished project trees
    for project in oc.projects_ready_for_review(b):
        await session_hygiene.ensure_fresh_orchestrator_session(MOM_SESSION)
        await runner.run_turn(MOM_SESSION, agent_policies.build_project_review_prompt(
            project["title"], _project_tree_digest(project)))
    b = oc.collect()

    # 4. Dispatch ready workers up to capacity (count in-progress WORKER_UNITS
    #    only — in-progress parent tasks must not starve worker dispatch).
    running = oc.running_worker_count(b)
    for task in oc.select_ready_workers(b, running, cfg.max_workers):
        await _dispatch_worker(runner, task)

    await _emit_board_digest(b, cfg.max_workers, throttle_info or {})
    _maybe_sync_external_board()


_tick_no = 0


def _maybe_sync_external_board() -> None:
    """Fire-and-forget external-board sync every N ticks (a Notion NL round trip
    can take minutes and must never stretch the tick). Opt-in via employee config."""
    global _tick_no
    _tick_no += 1
    emp = employee_config.load()
    if not (emp.employee_enabled and emp.board_sync_enabled):
        return
    if _tick_no % emp.board_sync_every_ticks:
        return
    asyncio.create_task(external_board.run_sync(emp))


async def _dispatch_worker(runner, task: dict) -> None:
    from devscope_bridge.schedule_setup import runtime_for_task

    name = f"worker-{task['id']}"
    agent, mode = runtime_for_task(task)
    task_store.update_task(task["id"], status="in_progress", assignee_session=name)
    task_store.add_log(task["id"], actor=name, message=f"dispatched ({agent}/{mode})")
    mark_long_running(name)
    ok = False
    try:
        await session_hygiene.reset_for_fresh_turn(name)
        ok = await runner.run_turn(
            name,
            agent_policies.build_worker_prompt(
                task["id"], task["title"],
                task.get("instruction") or task["title"],
                autonomy=task.get("autonomy", "guarded"),
                schedule_id=task.get("schedule_id")),
            mode=mode,
            agent=agent,
            timeout_s=WORKER_TIMEOUT_S,
            cwd=task.get("project_path"),
        )
    finally:
        clear_long_running(name)
        if orchestrator_config.load().auto_hygiene_enabled:
            await session_hygiene.cleanup_worker_session(name, task["id"])
    row = task_store.get_task(task["id"])
    if row and row["status"] == "in_progress" and not ok:
        task_store.update_task(
            task["id"],
            status="failed",
            result_summary=f"Worker turn timed out after {int(WORKER_TIMEOUT_S)}s",
        )
        task_store.add_log(task["id"], actor=name, message="dispatch timeout")


def _status_counts(b: oc.Buckets) -> dict[str, int]:
    return {
        "new": len(b.new_tasks),
        "assigned": len(b.assigned_tasks),
        "ready": len(b.ready_workers),
        "in_progress": len(b.in_progress),
        "awaiting_approval": len(b.pending_approvals),
        "approved": len(b.approved_tasks),
    }


async def _emit_board_digest(b: oc.Buckets, worker_cap: int, throttle: dict) -> None:
    counts = _status_counts(b)
    queued = counts["new"] + counts["assigned"] + counts["ready"]
    running = counts["in_progress"]
    util = throttle.get("utilization")
    util_note = f" · quota {util:.0f}%" if isinstance(util, (int, float)) else ""
    summary = (
        f"תור {queued} · רץ {running} · מכסה {worker_cap}{util_note}"
    )
    try:
        await board_relay.emit_task_digest(summary, counts)
    except Exception:
        logger.debug("board digest broadcast failed", exc_info=True)


# ── asyncio loop (started from main.lifespan) ──────────────────────────────
_loop_task: asyncio.Task | None = None


async def _loop(runner) -> None:
    settings = orchestrator_config.load()
    logger.info(
        "orchestrator loop started (tick=%ss, max_workers=%d)",
        settings.tick_seconds, settings.max_workers,
    )
    while True:
        settings = orchestrator_config.load()
        if settings.paused:
            logger.debug("orchestrator paused — skipping tick")
            await asyncio.sleep(min(30, settings.tick_seconds))
            continue
        base_cfg = settings.to_config()
        effective, throttle = await orchestrator_throttle.effective_max_workers(settings)
        cfg = OrchestratorConfig(
            tick_seconds=base_cfg.tick_seconds,
            max_workers=effective,
            domains=base_cfg.domains,
        )
        try:
            await run_tick(runner, cfg, throttle_info=throttle)
        except Exception:  # never let one bad tick kill the loop
            logger.exception("orchestrator tick failed")
        await asyncio.sleep(settings.tick_seconds)


def start_loop(runner, cfg: OrchestratorConfig | None = None) -> None:
    global _loop_task
    if _loop_task and not _loop_task.done():
        return
    if cfg is not None:
        orchestrator_config.save(orchestrator_config.OrchestratorSettings(
            tick_seconds=cfg.tick_seconds,
            max_workers=cfg.max_workers,
        ))
    _loop_task = asyncio.create_task(_loop(runner))


async def stop_loop() -> None:
    global _loop_task
    if _loop_task:
        _loop_task.cancel()
        try:
            await _loop_task
        except asyncio.CancelledError:
            pass
        _loop_task = None
