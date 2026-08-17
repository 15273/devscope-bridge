"""REST routes for orchestrator config and task board snapshot."""

from __future__ import annotations

import json

from fastapi import APIRouter
from pydantic import BaseModel

from devscope_bridge import orchestrator_config, orchestrator_core as oc, orchestrator_throttle, task_store
from devscope_bridge import board_state, task_usage

router = APIRouter(prefix="/orchestrator", tags=["orchestrator"])


class OrchestratorConfigBody(BaseModel):
    tick_seconds: int | None = None
    max_workers: int | None = None
    quota_throttle_enabled: bool | None = None
    quota_high_utilization: int | None = None
    quota_mid_utilization: int | None = None
    paused: bool | None = None


class MomReportBody(BaseModel):
    report: str


def _merge_settings(current: orchestrator_config.OrchestratorSettings, body: OrchestratorConfigBody):
    data = current.clamp().__dict__.copy()
    for key, val in body.model_dump(exclude_none=True).items():
        data[key] = val
    return orchestrator_config.OrchestratorSettings(**data).clamp()


def _count_by_status(tasks: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for task in tasks:
        st = task.get("status") or "unknown"
        counts[st] = counts.get(st, 0) + 1
    return counts


def _enrich_approvals(pending: list[dict]) -> list[dict]:
    enriched: list[dict] = []
    for row in pending:
        task = task_store.get_task(row["task_id"])
        try:
            payload = json.loads(row.get("payload_json") or "{}")
        except json.JSONDecodeError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {"value": payload}
        enriched.append({
            "id": row["id"],
            "task_id": row["task_id"],
            "action": row.get("action") or "",
            "status": row["status"],
            "created_at": row.get("created_at"),
            "title": task["title"] if task else row["task_id"],
            "task_status": task.get("status") if task else None,
            "payload": payload,
        })
    return enriched


@router.get("/config")
async def get_orchestrator_config() -> dict:
    settings = orchestrator_config.load()
    effective, throttle = await orchestrator_throttle.effective_max_workers(settings)
    return {
        "config": settings.clamp().__dict__,
        "runtime": {
            "effective_max_workers": effective,
            "paused": settings.paused,
            "throttle": throttle,
        },
    }


@router.patch("/config")
async def patch_orchestrator_config(body: OrchestratorConfigBody) -> dict:
    current = orchestrator_config.load()
    saved = orchestrator_config.save(_merge_settings(current, body))
    effective, throttle = await orchestrator_throttle.effective_max_workers(saved)
    return {
        "config": saved.__dict__,
        "runtime": {
            "effective_max_workers": effective,
            "paused": saved.paused,
            "throttle": throttle,
        },
    }


@router.get("/board")
async def get_task_board(domain: str | None = None) -> dict:
    settings = orchestrator_config.load()
    effective, throttle = await orchestrator_throttle.effective_max_workers(settings)
    buckets = oc.collect()
    tasks = task_store.list_tasks(domain=domain) if domain else task_store.list_tasks()
    tasks.sort(key=lambda t: t.get("updated_at") or "", reverse=True)
    tasks = task_usage.enrich_tasks_with_rollups(tasks)
    for task in tasks:
        if not task.get("parent_id") and task.get("kind") != "worker_unit":
            task["progress"] = oc.project_progress(task["id"])
    pending = task_store.list_pending_approvals()
    state = board_state.load()
    return {
        "config": settings.clamp().__dict__,
        "runtime": {
            "effective_max_workers": effective,
            "paused": settings.paused,
            "running_workers": len(buckets.in_progress),
            "queued_ready": len(buckets.new_tasks) + len(buckets.assigned_tasks) + len(buckets.ready_workers),
            "throttle": throttle,
            "last_tick_at": state.last_tick_at,
            "next_tick_at": state.next_tick_at,
            "completed_24h": task_store.count_tasks_completed_since(24),
            "usage_24h": task_store.aggregate_task_usage(24),
        },
        "mom": {
            "report": state.last_mom_report,
            "report_at": state.last_mom_report_at,
        },
        "counts": _count_by_status(tasks),
        "tasks": tasks[:120],
        "pending_approvals": _enrich_approvals(pending),
        "schedules": task_store.list_schedules(),
    }


@router.post("/mom-report")
def save_mom_report(body: MomReportBody) -> dict:
    state = board_state.set_mom_report(body.report)
    return {"ok": True, "report_at": state.last_mom_report_at}
