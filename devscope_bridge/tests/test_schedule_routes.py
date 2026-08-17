# devscope_bridge/tests/test_schedule_routes.py
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import patch

from devscope_bridge import task_store
from devscope_bridge import schedule_setup as setup_svc
from devscope_bridge.schedule_routes import router as schedule_router


@pytest.fixture
def client(tmp_path):
    task_store.set_db_path(tmp_path / "agent_tasks.db")
    task_store.init_db()
    app = FastAPI()
    app.include_router(schedule_router)
    yield TestClient(app)
    task_store.set_db_path(None)


def test_create_and_patch_playbook(client):
    res = client.post(
        "/schedules",
        json={
            "title": "LinkedIn post",
            "template": {
                "title": "LinkedIn post",
                "kind": "mom_task",
                "domain": "browser",
                "instruction": "Publish weekly post",
                "recurrence": {"daily_at": "09:00"},
            },
            "playbook": {"site": "linkedin.com", "selectors": {"composer": ".ql-editor"}},
            "next_run_at": "2026-06-15 09:00:00",
        },
    )
    assert res.status_code == 201
    sid = res.json()["id"]

    patch = client.post(
        f"/schedules/{sid}/playbook",
        json={"patch": {"selectors": {"publish": "button.primary"}, "workflow": ["Post"]}},
    )
    assert patch.status_code == 200
    pb = patch.json()["playbook"]
    assert pb["selectors"]["composer"] == ".ql-editor"
    assert pb["selectors"]["publish"] == "button.primary"
    assert "Post" in pb["workflow"]


def test_setup_start_creates_draft(client, tmp_path, monkeypatch):
    setup_dir = tmp_path / "schedule_setups"
    monkeypatch.setattr(setup_svc, "_SETUP_DIR", setup_dir)
    monkeypatch.setattr(setup_svc, "_ACTIVE_FILE", setup_dir / "active.json")
    with patch("devscope_bridge.schedule_setup.session_store.get_session", return_value=None):
        with patch("devscope_bridge.schedule_setup.session_store.create_session_metadata"):
            res = client.post(
                "/schedules/setup/start",
                json={
                    "title": "Weekly post",
                    "goal": "Post on LinkedIn",
                    "entry_url": "https://linkedin.com/feed/",
                    "domain": "browser",
                    "agent": "claude",
                    "setup_mode": "inspect",
                },
            )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["draft"]["id"]
    assert setup_dir.is_dir()
