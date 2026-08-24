# devscope_bridge/tests/test_schedule_question_flow.py
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from devscope_bridge import task_store
from devscope_bridge.task_routes import router as task_router


@pytest.fixture
def client(tmp_path):
    task_store.set_db_path(tmp_path / "agent_tasks.db")
    task_store.init_db()
    app = FastAPI()
    app.include_router(task_router)
    yield TestClient(app)
    task_store.set_db_path(None)


def _schedule_task_and_run():
    sid = task_store.add_schedule(
        title="Daily digest",
        template={"title": "Daily digest", "instruction": "do it",
                  "recurrence": {"daily_at": "09:00"}},
        next_run_at="2099-01-01 09:00:00",
    )
    tid = task_store.create_task(title="run", kind="worker_unit",
                                 instruction="do it", schedule_id=sid)
    run_id = task_store.create_schedule_run(sid, tid)
    return sid, tid, run_id


def test_question_moves_run_to_waiting_user_and_answer_resumes(client):
    sid, tid, run_id = _schedule_task_and_run()

    res = client.post(
        f"/tasks/{tid}/request-approval",
        json={"action": "question", "payload": {"question": "לפרסם?"}},
    )
    assert res.status_code == 200

    run = task_store.get_schedule_run(run_id)
    assert run["status"] == "waiting_user"
    assert run["question_text"] == "לפרסם?"
    assert run["question_importance"] == "important"

    res = client.post(f"/tasks/{tid}/answer", json={"answer": "כן"})
    assert res.status_code == 200

    run = task_store.get_schedule_run(run_id)
    assert run["status"] == "running"
    assert run["answered_by"] == "user"
    assert run["answer_text"] == "כן"


def test_routine_importance_claim_is_recorded(client):
    sid, tid, run_id = _schedule_task_and_run()
    client.post(
        f"/tasks/{tid}/request-approval",
        json={"action": "question",
              "payload": {"question": "איזה צבע?", "importance": "routine"}},
    )
    run = task_store.get_schedule_run(run_id)
    assert run["status"] == "waiting_user"
    assert run["question_importance"] == "routine"


def test_non_schedule_task_question_untouched(client):
    tid = task_store.create_task(title="plain", kind="worker_unit", instruction="x")
    res = client.post(
        f"/tasks/{tid}/request-approval",
        json={"action": "question", "payload": {"question": "מה?"}},
    )
    assert res.status_code == 200
    res = client.post(f"/tasks/{tid}/answer", json={"answer": "זה"})
    assert res.status_code == 200
