import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from devscope_bridge import task_store, task_routes


@pytest.fixture
def client(tmp_path):
    task_store.set_db_path(tmp_path / "agent_tasks.db")
    task_store.init_db()
    app = FastAPI()
    app.include_router(task_routes.router)
    yield TestClient(app)
    task_store.set_db_path(None)


def test_create_then_list_task(client):
    r = client.post("/tasks", json={"title": "Check inbox", "kind": "mom_task"})
    assert r.status_code == 201
    tid = r.json()["id"]
    r2 = client.get("/tasks")
    ids = [t["id"] for t in r2.json()["tasks"]]
    assert tid in ids


def test_update_with_note_writes_log(client):
    tid = client.post("/tasks", json={"title": "A", "kind": "worker_unit"}).json()["id"]
    r = client.post(f"/tasks/{tid}/update",
                    json={"status": "in_progress", "note": "started browsing"})
    assert r.status_code == 200
    logs = client.get(f"/tasks/{tid}").json()["logs"]
    assert any(l["message"] == "started browsing" for l in logs)


def test_request_approval_sets_awaiting_status(client):
    tid = client.post("/tasks", json={"title": "Send", "kind": "worker_unit"}).json()["id"]
    r = client.post(f"/tasks/{tid}/request-approval",
                    json={"action": "send_email", "payload": {"to": "x@y.com"}})
    assert r.status_code == 200
    assert client.get(f"/tasks/{tid}").json()["task"]["status"] == "awaiting_approval"


def test_approve_flips_task_to_approved(client):
    tid = client.post("/tasks", json={"title": "Send", "kind": "worker_unit"}).json()["id"]
    client.post(f"/tasks/{tid}/request-approval", json={"action": "send_email"})
    r = client.post(f"/tasks/{tid}/approve")
    assert r.status_code == 200
    assert client.get(f"/tasks/{tid}").json()["task"]["status"] == "approved"


def test_reject_cancels_task(client):
    tid = client.post("/tasks", json={"title": "Send", "kind": "worker_unit"}).json()["id"]
    client.post(f"/tasks/{tid}/request-approval", json={"action": "delete"})
    r = client.post(f"/tasks/{tid}/reject")
    assert r.status_code == 200
    assert client.get(f"/tasks/{tid}").json()["task"]["status"] == "cancelled"


def test_duplicate_request_approval_returns_same_id(client):
    tid = client.post("/tasks", json={"title": "Dup", "kind": "worker_unit"}).json()["id"]
    r1 = client.post(f"/tasks/{tid}/request-approval", json={"action": "do_thing"})
    r2 = client.post(f"/tasks/{tid}/request-approval", json={"action": "do_thing"})
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["approval_id"] == r2.json()["approval_id"]


def test_create_task_defaults_autonomy_guarded(client):
    r = client.post("/tasks", json={"title": "A", "kind": "mom_task"})
    assert r.status_code == 201
    assert r.json()["autonomy"] == "guarded"


def test_create_task_accepts_e2e(client):
    r = client.post("/tasks", json={"title": "A", "kind": "mom_task", "autonomy": "e2e"})
    assert r.status_code == 201
    tid = r.json()["id"]
    assert client.get(f"/tasks/{tid}").json()["task"]["autonomy"] == "e2e"


def test_create_task_rejects_invalid_autonomy(client):
    r = client.post("/tasks", json={"title": "A", "kind": "mom_task", "autonomy": "wild"})
    assert r.status_code == 422


def test_worker_unit_inherits_autonomy_through_api(client):
    parent = client.post("/tasks", json={"title": "P", "kind": "mom_task",
                                          "autonomy": "e2e"}).json()["id"]
    child = client.post("/tasks", json={"title": "C", "kind": "worker_unit",
                                        "parent_id": parent}).json()["id"]
    assert client.get(f"/tasks/{child}").json()["task"]["autonomy"] == "e2e"
