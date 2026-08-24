"""REST routes for recurring schedules and playbook memory."""

from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, HTTPException

from devscope_bridge import task_homes, task_store
from devscope_bridge.schedule_models import (
    ScheduleCreateBody,
    ScheduleDiscoverBody,
    ScheduleMemoryBody,
    SchedulePlaybookPatchBody,
    ScheduleRunReportBody,
    ScheduleSetupInstructionBody,
    ScheduleSetupMetaBody,
    ScheduleSetupPatchBody,
    ScheduleSetupStartBody,
    ScheduleStewardBody,
    ScheduleUpdateBody,
)
from devscope_bridge.schedule_discover import discover_playbook
from devscope_bridge.schedule_playbook import merge_playbook, parse_playbook
from devscope_bridge import schedule_setup as setup_svc

router = APIRouter(prefix="/schedules", tags=["schedules"])


def _enrich(sched: dict) -> dict:
    out = dict(sched)
    out["playbook"] = parse_playbook(out.pop("playbook", None))
    if "template_json" in out:
        try:
            out["template"] = json.loads(out.pop("template_json") or "{}")
        except json.JSONDecodeError:
            out["template"] = {}
    return out


@router.get("")
def list_schedules() -> dict:
    return {"schedules": [_enrich(s) for s in task_store.list_schedules()]}


@router.post("/discover")
async def discover_schedule_playbook(body: ScheduleDiscoverBody) -> dict:
    """Quick one-shot site map via Claude or Cursor + browser MCP."""
    result = await discover_playbook(
        entry_url=body.entry_url,
        goal=body.goal,
        session_name=body.session,
        domain=body.domain,
        agent=body.agent,
    )
    if not result.get("ok"):
        return {"ok": False, "error": result.get("error", "discover failed"), "data": result}
    return {"ok": True, "data": result}


@router.post("/setup/start")
async def start_setup(body: ScheduleSetupStartBody) -> dict:
    """Create a dedicated setup draft + sched-setup-* session for deep research."""
    draft = await setup_svc.start_setup(
        title=body.title,
        goal=body.goal,
        entry_url=body.entry_url,
        domain=body.domain,
        agent=body.agent,
        setup_mode=body.setup_mode,
        instruction=body.instruction,
    )
    return {"ok": True, "draft": draft}


@router.get("/setup/drafts/{draft_id}")
def get_setup_draft(draft_id: str) -> dict:
    draft = setup_svc.get_draft(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="setup draft not found")
    return {"ok": True, "draft": draft}


@router.post("/setup/drafts/{draft_id}/bootstrap")
async def bootstrap_setup(draft_id: str) -> dict:
    result = await setup_svc.bootstrap_session(draft_id)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("error", "bootstrap failed"))
    return result


@router.post("/setup/drafts/{draft_id}/playbook")
def patch_setup_playbook(draft_id: str, body: ScheduleSetupPatchBody) -> dict:
    draft = setup_svc.update_playbook(draft_id, body.patch)
    if not draft:
        raise HTTPException(status_code=404, detail="setup draft not found")
    return {"ok": True, "draft": draft}


@router.post("/setup/drafts/{draft_id}/instruction")
def patch_setup_instruction(draft_id: str, body: ScheduleSetupInstructionBody) -> dict:
    draft = setup_svc.set_instruction(draft_id, body.instruction)
    if not draft:
        raise HTTPException(status_code=404, detail="setup draft not found")
    return {"ok": True, "draft": draft}


@router.post("/setup/drafts/{draft_id}/meta")
def patch_setup_meta(draft_id: str, body: ScheduleSetupMetaBody) -> dict:
    draft = setup_svc.set_meta(draft_id, body.model_dump(exclude_none=True))
    if not draft:
        raise HTTPException(status_code=404, detail="setup draft not found")
    return {"ok": True, "draft": draft}


@router.post("/setup/drafts/{draft_id}/commit")
def commit_setup_draft(draft_id: str) -> dict:
    sched, error = setup_svc.commit_draft(draft_id)
    if error == "draft not found":
        raise HTTPException(status_code=404, detail=error)
    if error:
        raise HTTPException(status_code=400, detail=error)
    return _enrich(sched)


@router.post("/setup/drafts/{draft_id}/complete")
def complete_setup_draft(draft_id: str) -> dict:
    draft = setup_svc.complete_draft(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="setup draft not found")
    return {"ok": True, "draft": draft}


@router.post("", status_code=201)
def create_schedule(body: ScheduleCreateBody) -> dict:
    sid = task_store.add_schedule(
        title=body.title,
        template=body.template.model_dump(exclude_none=True),
        playbook=body.playbook,
        cron_expr=body.cron_expr,
        next_run_at=body.next_run_at,
        enabled=body.enabled,
    )
    sched = task_store.get_schedule(sid)
    return _enrich(sched) if sched else {"id": sid}


@router.get("/{schedule_id}")
def get_schedule(schedule_id: int) -> dict:
    sched = task_store.get_schedule(schedule_id)
    if sched is None:
        raise HTTPException(status_code=404, detail="schedule not found")
    return _enrich(sched)


@router.patch("/{schedule_id}")
def update_schedule(schedule_id: int, body: ScheduleUpdateBody) -> dict:
    if task_store.get_schedule(schedule_id) is None:
        raise HTTPException(status_code=404, detail="schedule not found")
    fields = body.model_dump(exclude_none=True)
    if "template" in fields:
        fields["template"] = fields["template"]
    task_store.update_schedule(schedule_id, **fields)
    sched = task_store.get_schedule(schedule_id)
    return _enrich(sched) if sched else {}


def _require_schedule(schedule_id: int) -> dict:
    sched = task_store.get_schedule(schedule_id)
    if sched is None:
        raise HTTPException(status_code=404, detail="schedule not found")
    return sched


@router.get("/{schedule_id}/runs")
def list_runs(schedule_id: int) -> dict:
    _require_schedule(schedule_id)
    return {"runs": task_store.list_schedule_runs(schedule_id)}


@router.post("/{schedule_id}/runs/report")
def report_run(schedule_id: int, body: ScheduleRunReportBody) -> dict:
    _require_schedule(schedule_id)
    run = task_store.get_run_for_task(body.task_id)
    if run is None or run["schedule_id"] != schedule_id:
        raise HTTPException(status_code=404, detail="run not found for task")
    if run["status"] != "running":
        return {"ok": True, "already_closed": True, "run_id": run["id"]}
    task_store.finish_schedule_run(
        run["id"],
        status=body.status,
        digest_text=body.digest,
        artifacts=body.artifacts,
    )
    if body.memory_note:
        task_homes.append_memory(schedule_id, body.memory_note)
    return {"ok": True, "run_id": run["id"]}


@router.get("/{schedule_id}/memory")
def get_memory(schedule_id: int) -> dict:
    _require_schedule(schedule_id)
    return {"memory": task_homes.read_memory(schedule_id)}


@router.put("/{schedule_id}/memory")
def put_memory(schedule_id: int, body: ScheduleMemoryBody) -> dict:
    _require_schedule(schedule_id)
    task_homes.write_memory(schedule_id, body.content)
    return {"ok": True}


@router.get("/{schedule_id}/reports")
def list_run_reports(schedule_id: int) -> dict:
    _require_schedule(schedule_id)
    return {"reports": task_homes.list_reports(schedule_id)}


@router.post("/{schedule_id}/run")
def run_now(schedule_id: int) -> dict:
    _require_schedule(schedule_id)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    task_store.set_schedule_next_run(schedule_id, now)
    return {"ok": True, "next_run_at": now}


@router.post("/{schedule_id}/steward")
async def steward(schedule_id: int, body: ScheduleStewardBody) -> dict:
    result = await setup_svc.steward_message(schedule_id, body.message)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("error", "steward failed"))
    return result


@router.post("/{schedule_id}/playbook")
def patch_playbook(schedule_id: int, body: SchedulePlaybookPatchBody) -> dict:
    sched = task_store.get_schedule(schedule_id)
    if sched is None:
        raise HTTPException(status_code=404, detail="schedule not found")
    merged = merge_playbook(parse_playbook(sched.get("playbook")), body.patch)
    task_store.update_schedule(schedule_id, playbook=merged)
    return {"playbook": merged}


@router.delete("/{schedule_id}")
def delete_schedule(schedule_id: int) -> dict:
    if task_store.get_schedule(schedule_id) is None:
        raise HTTPException(status_code=404, detail="schedule not found")
    task_store.delete_schedule(schedule_id)
    return {"ok": True}
