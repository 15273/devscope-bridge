"""REST routes for recurring schedules and playbook memory."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

from devscope_bridge import task_store
from devscope_bridge.schedule_models import (
    ScheduleCreateBody,
    ScheduleDiscoverBody,
    SchedulePlaybookPatchBody,
    ScheduleSetupInstructionBody,
    ScheduleSetupPatchBody,
    ScheduleSetupStartBody,
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


@router.get("/setup/active")
def get_active_setup() -> dict:
    draft = setup_svc.load_active()
    return {"ok": True, "draft": draft}


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
