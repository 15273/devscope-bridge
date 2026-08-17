# devscope_bridge/tests/test_employee_comms.py
"""Tests for employee comms fan-out, digest composition, and builtin schedules."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from devscope_bridge import employee_comms as ec
from devscope_bridge import orchestrator_core as oc
from devscope_bridge import task_store
from devscope_bridge.employee_config import EmployeeSettings


@pytest.fixture()
def temp_db(tmp_path):
    task_store.set_db_path(tmp_path / "tasks.db")
    task_store.init_db()
    yield
    task_store.set_db_path(None)


@pytest.mark.asyncio
async def test_notify_respects_master_switch_and_channel_flags():
    event = ec.CommsEvent(kind="question", title="t", body="b", task_id=None)
    with patch.object(ec, "_send_panel", new=AsyncMock()) as panel, \
         patch.object(ec, "_send_whatsapp", new=AsyncMock()) as wa:
        await ec.notify(event, EmployeeSettings())  # employee disabled
        panel.assert_not_awaited()

        cfg = EmployeeSettings(employee_enabled=True)
        cfg.channels["whatsapp"] = False
        await ec.notify(event, cfg)
        panel.assert_awaited_once()
        wa.assert_not_awaited()


@pytest.mark.asyncio
async def test_notify_channel_failure_does_not_break_others():
    event = ec.CommsEvent(kind="blocker", title="t", body="b")
    cfg = EmployeeSettings(employee_enabled=True)
    cfg.channels["whatsapp"] = True
    boom = AsyncMock(side_effect=RuntimeError("boom"))
    with patch.object(ec, "_send_panel", new=boom), \
         patch.object(ec, "_send_whatsapp", new=AsyncMock()) as wa:
        await ec.notify(event, cfg)  # must not raise
        wa.assert_awaited_once()


def test_digest_body_counts(temp_db):
    task_store.create_task(title="done1", kind="worker_unit", status="done")
    root = task_store.create_task(title="Big project", kind="mom_task",
                                  status="in_progress")
    task_store.create_task(title="m1", kind="domain_task", parent_id=root, status="done")
    qid = task_store.create_task(title="asker", kind="worker_unit")
    task_store.request_approval(qid, action="question", payload={"question": "?"})

    body = ec._digest_body()
    assert "2 tasks" in body
    assert "Big project: 1/1 steps (100%)" in body
    assert "Open questions waiting for you: 1." in body


def test_ensure_digest_schedule_seeds_once_with_next_run(temp_db):
    cfg = EmployeeSettings(digest_daily_at="18:00")
    ec.ensure_digest_schedule(cfg)
    ec.ensure_digest_schedule(cfg)  # idempotent
    schedules = [s for s in task_store.list_schedules() if ec._is_digest_schedule(s)]
    assert len(schedules) == 1
    assert schedules[0]["next_run_at"]  # non-NULL or due_schedules never fires
    assert schedules[0]["template"]["recurrence"]["daily_at"] == "18:00"


@pytest.mark.asyncio
async def test_builtin_schedule_runs_instead_of_creating_task(temp_db):
    ec.ensure_digest_schedule(EmployeeSettings())
    sched = next(s for s in task_store.list_schedules() if ec._is_digest_schedule(s))
    task_store.set_schedule_next_run(sched["id"], "2000-01-01 00:00:00")

    ran = AsyncMock()
    with patch.dict(ec.BUILTINS, {"daily_digest": ran}):
        count = oc.materialise_due_schedules(now="2000-01-01 00:00:01")
    assert count == 1
    assert task_store.list_tasks(status="new") == []  # no task materialised
    ran.assert_called_once()
    updated = task_store.list_schedules()[0]
    assert updated["next_run_at"] > "2000-01-01 00:00:01"  # advanced, no hot loop
