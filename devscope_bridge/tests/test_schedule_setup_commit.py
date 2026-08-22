# devscope_bridge/tests/test_schedule_setup_commit.py
from datetime import datetime
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from devscope_bridge import schedule_setup as setup_svc
from devscope_bridge import task_store
from devscope_bridge.schedule_routes import router as schedule_router


@pytest.fixture
def client(tmp_path, monkeypatch):
    task_store.set_db_path(tmp_path / "agent_tasks.db")
    task_store.init_db()
    monkeypatch.setattr(setup_svc, "_SETUP_DIR", tmp_path / "schedule_setups")
    app = FastAPI()
    app.include_router(schedule_router)
    yield TestClient(app)
    task_store.set_db_path(None)


def _start(client, **overrides):
    body = {"title": "פוסט שבועי"}
    body.update(overrides)
    with patch("devscope_bridge.schedule_setup.session_store.get_session", return_value=None):
        with patch("devscope_bridge.schedule_setup.session_store.create_session_metadata"):
            res = client.post("/schedules/setup/start", json=body)
    assert res.status_code == 200
    return res.json()["draft"]


def test_start_with_title_only(client):
    draft = _start(client)
    assert draft["title"] == "פוסט שבועי"
    assert draft["goal"] == ""
    assert draft["entry_url"] == ""
    assert draft["recurrence"] == {}
    assert draft["autonomy_policy"] is None


def test_meta_then_commit_creates_schedule(client):
    draft = _start(client)
    did = draft["id"]

    meta = client.post(
        f"/schedules/setup/drafts/{did}/meta",
        json={
            "recurrence": {"daily_at": "09:00"},
            "autonomy_policy": "מותר לבחור ניסוח, אסור לפרסם בלי אישור",
            "goal": "פוסט לינקדאין שבועי",
        },
    )
    assert meta.status_code == 200
    assert meta.json()["draft"]["recurrence"] == {"daily_at": "09:00"}

    inst = client.post(
        f"/schedules/setup/drafts/{did}/instruction",
        json={"instruction": "כתוב ופרסם פוסט"},
    )
    assert inst.status_code == 200

    commit = client.post(f"/schedules/setup/drafts/{did}/commit")
    assert commit.status_code == 200
    sched = commit.json()
    tmpl = sched["template"]
    assert tmpl["instruction"] == "כתוב ופרסם פוסט"
    assert tmpl["autonomy_policy"] == "מותר לבחור ניסוח, אסור לפרסם בלי אישור"
    assert tmpl["recurrence"] == {"daily_at": "09:00"}

    # next run is today-or-tomorrow at 09:00
    nra = datetime.strptime(sched["next_run_at"], "%Y-%m-%d %H:%M:%S")
    assert (nra.hour, nra.minute) == (9, 0)
    assert nra > datetime.now() or nra.date() == datetime.now().date()

    updated = setup_svc.get_draft(did)
    assert updated["status"] == "committed"
    assert updated["schedule_id"] == sched["id"]


def test_commit_without_recurrence_400(client):
    draft = _start(client)
    did = draft["id"]
    client.post(f"/schedules/setup/drafts/{did}/instruction",
                json={"instruction": "משהו"})
    res = client.post(f"/schedules/setup/drafts/{did}/commit")
    assert res.status_code == 400


def test_commit_without_instruction_or_goal_400(client):
    draft = _start(client)
    did = draft["id"]
    client.post(f"/schedules/setup/drafts/{did}/meta",
                json={"recurrence": {"daily_at": "09:00"}})
    res = client.post(f"/schedules/setup/drafts/{did}/commit")
    assert res.status_code == 400


def test_find_draft_by_session(client):
    draft = _start(client)
    found = setup_svc.find_draft_by_session(draft["session_name"])
    assert found and found["id"] == draft["id"]
    assert setup_svc.find_draft_by_session("no-such-session") is None
