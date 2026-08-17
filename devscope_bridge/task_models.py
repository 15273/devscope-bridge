"""Pydantic request/response bodies for the /tasks routes."""

from pydantic import BaseModel


class TaskCreateBody(BaseModel):
    title: str
    kind: str = "mom_task"
    detail: str | None = None
    source: str | None = "board"
    domain: str | None = None
    parent_id: str | None = None
    priority: int = 0
    instruction: str | None = None
    scheduled_for: str | None = None
    autonomy: str | None = None   # None → store inherits from parent, else defaults to "guarded"
    project_path: str | None = None  # None → inherited from parent; workers run with this cwd


class TaskUpdateBody(BaseModel):
    status: str | None = None
    domain: str | None = None
    priority: int | None = None
    assignee_session: str | None = None
    instruction: str | None = None
    result_summary: str | None = None
    artifact_path: str | None = None
    note: str | None = None          # appended to task_logs when present


class ApprovalRequestBody(BaseModel):
    action: str
    payload: dict | None = None


class LogBody(BaseModel):
    message: str
    actor: str | None = None


class AnswerBody(BaseModel):
    answer: str
