# devscope_bridge/tests/test_schedule_steward.py
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from devscope_bridge import task_homes, task_store
from devscope_bridge.schedule_routes import router as schedule_router


@pytest.fixture
def client(tmp_path):
    task_store.set_db_path(tmp_path / "agent_tasks.db")
    task_store.init_db()
    task_homes.set_base_dir(tmp_path / "task_homes")
    app = FastAPI()
    app.include_router(schedule_router)
    yield TestClient(app)
    task_store.set_db_path(None)
    task_homes.set_base_dir(None)


def test_steward_creates_session_and_sends_context(client):
    sid = task_store.add_schedule(
        title="פוסט שבועי",
        template={"title": "פוסט שבועי", "instruction": "פרסם פוסט",
                  "autonomy_policy": "בלי כסף", "recurrence": {"daily_at": "09:00"}},
        next_run_at="2099-01-01 09:00:00",
    )
    task_homes.write_memory(sid, "- selector השתנה")
    tid = task_store.create_task(title="run", kind="worker_unit", schedule_id=sid)
    rid = task_store.create_schedule_run(sid, tid)
    task_store.finish_schedule_run(rid, status="success", digest_text="פרסמתי בהצלחה")

    with patch("devscope_bridge.schedule_setup.session_store.get_session", return_value=None), \
         patch("devscope_bridge.schedule_setup.session_store.create_session_metadata") as create, \
         patch("devscope_bridge.schedule_setup.session_manager.run_prompt",
               new_callable=AsyncMock) as run_prompt:
        res = client.post(f"/schedules/{sid}/steward", json={"message": "מה קרה בריצה האחרונה?"})

    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["session_name"] == f"sched-steward-{sid}"
    create.assert_called_once()
    prompt = run_prompt.call_args.args[1]
    assert "פרסם פוסט" in prompt
    assert "בלי כסף" in prompt
    assert "selector השתנה" in prompt
    assert "פרסמתי בהצלחה" in prompt
    assert "מה קרה בריצה האחרונה?" in prompt


def test_steward_404_on_missing_schedule(client):
    res = client.post("/schedules/999/steward", json={"message": "הי"})
    assert res.status_code == 404
