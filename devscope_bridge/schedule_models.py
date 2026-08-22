"""Pydantic bodies for /schedules routes."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ScheduleTemplateBody(BaseModel):
    title: str | None = None
    kind: str = "mom_task"
    detail: str | None = None
    domain: str | None = None
    instruction: str | None = None
    autonomy: str | None = None
    autonomy_policy: str | None = None
    agent: str = Field(default="claude", pattern="^(claude|cursor)$")
    mode: str | None = Field(default="act", pattern="^(act|plan|inspect|test)$")
    recurrence: dict[str, Any] = Field(default_factory=dict)


class ScheduleSetupStartBody(BaseModel):
    title: str = "משימה חדשה"
    goal: str = ""
    entry_url: str = ""
    domain: str = "browser"
    agent: str = Field(default="claude", pattern="^(claude|cursor)$")
    setup_mode: str = Field(default="inspect", pattern="^(inspect|plan|act)$")
    instruction: str | None = None


class ScheduleSetupMetaBody(BaseModel):
    title: str | None = None
    recurrence: dict[str, Any] | None = None
    agent: str | None = Field(default=None, pattern="^(claude|cursor)$")
    autonomy_policy: str | None = Field(default=None, max_length=4_000)
    entry_url: str | None = None
    goal: str | None = None


class ScheduleSetupPatchBody(BaseModel):
    patch: dict[str, Any]


class ScheduleSetupInstructionBody(BaseModel):
    instruction: str


class ScheduleCreateBody(BaseModel):
    title: str
    template: ScheduleTemplateBody
    playbook: dict[str, Any] | None = None
    cron_expr: str | None = None
    next_run_at: str | None = None
    enabled: bool = True


class ScheduleUpdateBody(BaseModel):
    title: str | None = None
    template: ScheduleTemplateBody | None = None
    playbook: dict[str, Any] | None = None
    cron_expr: str | None = None
    next_run_at: str | None = None
    enabled: bool | None = None


class SchedulePlaybookPatchBody(BaseModel):
    patch: dict[str, Any]


class ScheduleRunReportBody(BaseModel):
    task_id: str
    digest: str = Field(max_length=4_000)
    artifacts: list[str] = Field(default_factory=list, max_length=50)
    memory_note: str | None = Field(default=None, max_length=2_000)
    status: str = Field(default="success", pattern="^(success|failed)$")


class ScheduleMemoryBody(BaseModel):
    content: str = Field(max_length=64_000)


class ScheduleDiscoverBody(BaseModel):
    entry_url: str
    goal: str
    session: str | None = None
    domain: str = "browser"
    agent: str = Field(default="claude", pattern="^(claude|cursor)$")
