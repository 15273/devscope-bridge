"""
orchestrator_core.py — PURE decision logic for the orchestrator tick.

Reads task_store and returns decisions (which tiers to wake, which workers to
dispatch, which schedules to materialise). Imports task_store ONLY — never
session_manager — so it is fully unit-testable.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from devscope_bridge import task_store
from devscope_bridge.schedule_playbook import (
    build_scheduled_instruction,
    parse_playbook,
)

_TS_FMT = "%Y-%m-%d %H:%M:%S"
_TERMINAL_STATUSES = {"done", "failed", "cancelled"}


@dataclass
class Buckets:
    new_tasks: list[dict] = field(default_factory=list)
    assigned_tasks: list[dict] = field(default_factory=list)
    ready_workers: list[dict] = field(default_factory=list)
    in_progress: list[dict] = field(default_factory=list)
    pending_approvals: list[dict] = field(default_factory=list)
    approved_tasks: list[dict] = field(default_factory=list)


def collect() -> Buckets:
    """Snapshot the board into decision buckets."""
    return Buckets(
        new_tasks=task_store.list_tasks(status="new"),
        assigned_tasks=task_store.list_tasks(status="assigned"),
        ready_workers=task_store.list_tasks(status="ready"),
        in_progress=task_store.list_tasks(status="in_progress"),
        pending_approvals=task_store.list_pending_approvals(),
        approved_tasks=task_store.list_tasks(status="approved"),
    )


def should_wake_mom(b: Buckets) -> bool:
    """Wake the MoM only when there is top-level triage to do."""
    return bool(b.new_tasks)


def domains_needing_triage(b: Buckets, domains: tuple[str, ...]) -> list[str]:
    """Domains that have assigned work waiting to be broken into worker_units."""
    present = {t["domain"] for t in b.assigned_tasks if t["domain"] in domains}
    return [d for d in domains if d in present]


def parents_ready_for_rollup(b: Buckets, domains: tuple[str, ...]) -> list[dict]:
    """In-progress parent tasks (in our domains) whose every worker_unit child has
    reached a terminal status. These need a domain-manager re-wake to synthesise the
    results and close the parent — otherwise the parent stays in_progress forever."""
    ready = []
    for parent in b.in_progress:
        if parent.get("kind") == "worker_unit" or parent.get("domain") not in domains:
            continue
        units = [c for c in task_store.list_tasks(parent_id=parent["id"])
                 if c.get("kind") == "worker_unit"]
        if units and all(c["status"] in _TERMINAL_STATUSES for c in units):
            ready.append(parent)
    return ready


def projects_ready_for_review(b: Buckets) -> list[dict]:
    """Top-level in-progress tasks (no parent) whose children are ALL terminal —
    the MoM should synthesise a result_summary and close (or re-plan) the project.
    Mirrors parents_ready_for_rollup one tier up; only trees with domain_task
    children qualify (flat parents are closed by their domain manager rollup)."""
    ready = []
    for root in b.in_progress:
        if root.get("parent_id") or root.get("kind") == "worker_unit":
            continue
        children = task_store.list_tasks(parent_id=root["id"])
        milestones = [c for c in children if c.get("kind") == "domain_task"]
        if milestones and all(c["status"] in _TERMINAL_STATUSES for c in children):
            ready.append(root)
    return ready


def project_progress(task_id: str) -> dict:
    """Recursive subtree progress: {total, done, failed, pct} (excludes the root)."""
    total = done = failed = 0
    stack = [task_id]
    while stack:
        for child in task_store.list_tasks(parent_id=stack.pop()):
            total += 1
            if child["status"] == "done":
                done += 1
            elif child["status"] in ("failed", "cancelled"):
                failed += 1
            stack.append(child["id"])
    pct = int(round(100 * done / total)) if total else 0
    return {"total": total, "done": done, "failed": failed, "pct": pct}


def requeue_approved_workers(b: Buckets) -> int:
    """Approved worker_units were never re-dispatched (latent gap) — requeue them
    as 'ready' so the dispatcher re-runs the worker with approval granted."""
    count = 0
    for task in b.approved_tasks:
        if task.get("kind") != "worker_unit":
            continue
        task_store.update_task(task["id"], status="ready")
        task_store.add_log(task["id"], actor="orchestrator",
                           message="approval granted — requeued as ready")
        count += 1
    return count


def running_worker_count(b: Buckets) -> int:
    """Worker slots in use = in-progress WORKER_UNITS only.

    Parent mom_task/domain_task are 'in_progress' while they delegate to children
    and must NOT count against worker capacity — otherwise a few stuck parents
    drive capacity to 0 and deadlock all worker dispatch (their children sit
    'ready' forever, so the parents never close: a self-sustaining deadlock).
    """
    return sum(1 for t in b.in_progress if t.get("kind") == "worker_unit")


def select_ready_workers(b: Buckets, running_count: int, max_workers: int) -> list[dict]:
    """Pick ready worker_units up to remaining capacity, highest parent priority first.

    Worker_units are created at priority 0 regardless of their parent's priority,
    so without ordering by the PARENT's priority a high-priority pipeline (e.g.
    company_enrichment at priority 8) would queue behind unrelated backlog. We sort
    ready units by their parent task's priority (descending); ties keep FIFO order.
    """
    capacity = max(0, max_workers - running_count)
    if capacity <= 0:
        return []
    parent_priority = {t["id"]: (t.get("priority") or 0) for t in task_store.list_tasks()}
    ordered = sorted(
        b.ready_workers,
        key=lambda w: parent_priority.get(w.get("parent_id"), w.get("priority") or 0),
        reverse=True,
    )
    return ordered[:capacity]


def _now() -> str:
    return datetime.now().strftime(_TS_FMT)


def _next_run_at(recurrence: dict, now: str) -> str:
    base = datetime.strptime(now, _TS_FMT)
    if "every_minutes" in recurrence:
        return (base + timedelta(minutes=int(recurrence["every_minutes"]))).strftime(_TS_FMT)
    if "daily_at" in recurrence:
        hh, mm = (int(x) for x in recurrence["daily_at"].split(":"))
        nxt = base.replace(hour=hh, minute=mm, second=0)
        if nxt <= base:
            nxt += timedelta(days=1)
        return nxt.strftime(_TS_FMT)
    # default: one hour out, prevents a missing recurrence from hot-looping
    return (base + timedelta(hours=1)).strftime(_TS_FMT)


def _run_builtin_schedule(name: str) -> bool:
    """Run a 'builtin' schedule template (e.g. the employee daily digest) as a
    fire-and-forget coroutine instead of materialising a task. Returns handled."""
    import asyncio

    from devscope_bridge import employee_comms

    fn = employee_comms.BUILTINS.get(name)
    if fn is None:
        return False
    try:
        asyncio.get_running_loop().create_task(fn())
    except RuntimeError:  # no loop (tests) — skip silently
        pass
    return True


def materialise_due_schedules(now: str | None = None) -> int:
    """Create a task from each due schedule and advance its next_run_at. Returns count."""
    now = now or _now()
    due = task_store.due_schedules(now=now)
    for sched in due:
        tmpl = json.loads(sched["template_json"])
        if tmpl.get("builtin"):
            _run_builtin_schedule(tmpl["builtin"])
            task_store.set_schedule_next_run(
                sched["id"], _next_run_at(tmpl.get("recurrence", {}), now))
            continue
        playbook = parse_playbook(sched.get("playbook_json"))
        base_instruction = tmpl.get("instruction")
        instruction = build_scheduled_instruction(base_instruction, playbook)
        tid = task_store.create_task(
            title=tmpl.get("title", sched["title"]),
            kind=tmpl.get("kind", "mom_task"),
            detail=tmpl.get("detail"),
            domain=tmpl.get("domain"),
            instruction=instruction,
            source="scheduled",
            status="new",
            autonomy=tmpl.get("autonomy"),
            schedule_id=sched["id"],
        )
        task_store.add_log(tid, actor="scheduler",
                           message=f"materialised from schedule #{sched['id']}")
        recurrence = tmpl.get("recurrence", {})
        task_store.set_schedule_next_run(sched["id"], _next_run_at(recurrence, now))
    return len(due)
