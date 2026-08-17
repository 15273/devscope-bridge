"""FastAPI routes for the agent task store. dev_bridge is the single SQLite writer."""

import logging

from fastapi import APIRouter, HTTPException

from devscope_bridge import task_store
from devscope_bridge import board_relay
from devscope_bridge import employee_comms
from devscope_bridge import task_usage
from devscope_bridge.task_models import (
    AnswerBody, ApprovalRequestBody, LogBody, TaskCreateBody, TaskUpdateBody,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("", status_code=201)
def create_task(body: TaskCreateBody) -> dict:
    try:
        tid = task_store.create_task(
            title=body.title, kind=body.kind, detail=body.detail, source=body.source,
            domain=body.domain, parent_id=body.parent_id, priority=body.priority,
            instruction=body.instruction, scheduled_for=body.scheduled_for,
            autonomy=body.autonomy, project_path=body.project_path,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    task_store.add_log(tid, actor=body.source or "system", message=f"created: {body.title}")
    task = task_store.get_task(tid)
    board_relay.notify_task_update(tid, body.title, task["status"], body.domain, "created")
    return task


@router.get("")
def list_tasks(status: str | None = None, domain: str | None = None,
               assignee_session: str | None = None, parent_id: str | None = None) -> dict:
    return {"tasks": task_store.list_tasks(
        status=status, domain=domain,
        assignee_session=assignee_session, parent_id=parent_id)}


@router.get("/{task_id}")
def get_task(task_id: str) -> dict:
    task = task_store.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    children = task_store.list_tasks(parent_id=task_id)
    enriched = task_usage.enrich_tasks_with_rollups([task, *children])
    return {"task": enriched[0], "logs": task_store.list_logs(task_id)}


@router.post("/{task_id}/update")
def update_task(task_id: str, body: TaskUpdateBody) -> dict:
    if task_store.get_task(task_id) is None:
        raise HTTPException(status_code=404, detail="task not found")
    before = task_store.get_task(task_id)
    fields = body.model_dump(exclude_none=True, exclude={"note"})
    try:
        task_store.update_task(task_id, **fields)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if body.note:
        task_store.add_log(task_id, actor=fields.get("assignee_session") or "agent",
                           message=body.note)
    task = task_store.get_task(task_id)
    if (
        before
        and task
        and before.get("status") != "done"
        and task.get("status") == "done"
        and task.get("schedule_id")
    ):
        task_store.touch_schedule_run(int(task["schedule_id"]), task_id, success=True)
    if task:
        board_relay.notify_task_update(
            task_id, task["title"], task["status"], task.get("domain"), body.note,
        )
    return task


@router.post("/{task_id}/log")
def add_log(task_id: str, body: LogBody) -> dict:
    if task_store.get_task(task_id) is None:
        raise HTTPException(status_code=404, detail="task not found")
    task_store.add_log(task_id, message=body.message, actor=body.actor)
    return {"ok": True}


@router.post("/{task_id}/request-approval")
def request_approval(task_id: str, body: ApprovalRequestBody) -> dict:
    task = task_store.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    existing = [a for a in task_store.list_pending_approvals() if a["task_id"] == task_id]
    if existing:
        return {"approval_id": existing[-1]["id"], "status": "awaiting_approval"}
    aid = task_store.request_approval(task_id, action=body.action, payload=body.payload)
    task_store.update_task(task_id, status="awaiting_approval")
    task_store.add_log(task_id, actor="agent",
                       message=f"approval requested: {body.action}")
    board_relay.notify_approval_request(
        task_id, task["title"], body.action, body.payload, approval_id=aid,
    )
    board_relay.notify_task_update(
        task_id, task["title"], "awaiting_approval", task.get("domain"), body.action,
    )
    employee_comms.notify_question(task, body.action, body.payload)
    return {"approval_id": aid, "status": "awaiting_approval"}


@router.post("/{task_id}/answer")
def answer_question(task_id: str, body: AnswerBody) -> dict:
    """Answer a pending action='question' approval: bake the answer into the
    instruction and requeue explicitly (ready for units, new for parents)."""
    task = task_store.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    pend = [a for a in task_store.list_pending_approvals() if a["task_id"] == task_id]
    if not pend:
        raise HTTPException(status_code=404, detail="no pending question")
    task_store.decide_approval(pend[-1]["id"], approved=True, answer_text=body.answer)
    instruction = (task.get("instruction") or task["title"]).rstrip()
    new_status = "ready" if task.get("kind") == "worker_unit" else "new"
    task_store.update_task(
        task_id,
        instruction=f"{instruction}\n\n## User answer\n{body.answer}",
        status=new_status,
    )
    task_store.add_log(task_id, actor="user", message=f"answered: {body.answer[:200]}")
    board_relay.notify_task_update(
        task_id, task["title"], new_status, task.get("domain"), "question answered",
    )
    return {"status": new_status}


@router.post("/{task_id}/approve")
def approve(task_id: str) -> dict:
    return _decide(task_id, approved=True)


@router.post("/{task_id}/reject")
def reject(task_id: str) -> dict:
    return _decide(task_id, approved=False)


def _decide(task_id: str, approved: bool) -> dict:
    pend = [a for a in task_store.list_pending_approvals() if a["task_id"] == task_id]
    if not pend:
        raise HTTPException(status_code=404, detail="no pending approval")
    task_store.decide_approval(pend[-1]["id"], approved=approved)
    new_status = "approved" if approved else "cancelled"
    task_store.update_task(task_id, status=new_status)
    task_store.add_log(task_id, actor="user",
                       message="approved" if approved else "rejected")
    task = task_store.get_task(task_id)
    if task:
        note = "approved" if approved else "rejected"
        board_relay.notify_task_update(
            task_id, task["title"], new_status, task.get("domain"), note,
        )
    return {"status": new_status}


@router.post("/{task_id}/cancel")
def cancel(task_id: str) -> dict:
    if task_store.get_task(task_id) is None:
        raise HTTPException(status_code=404, detail="task not found")
    task_store.update_task(task_id, status="cancelled")
    task_store.add_log(task_id, actor="user", message="cancelled")
    return {"status": "cancelled"}
