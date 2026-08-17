"""Board endpoint enriches pending approvals for the panel."""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from devscope_bridge import orchestrator_routes, task_store


@pytest.fixture
def client(tmp_path):
    task_store.set_db_path(tmp_path / "agent_tasks.db")
    task_store.init_db()
    app = FastAPI()
    app.include_router(orchestrator_routes.router)
    yield TestClient(app)
    task_store.set_db_path(None)


def test_board_enriches_pending_approvals(client):
    tid = task_store.create_task(title="Send report", kind="worker_unit", status="in_progress")
    task_store.request_approval(tid, action="send", payload={"to": "boss@co.com"})
    task_store.update_task(tid, status="awaiting_approval")

    body = client.get("/orchestrator/board").json()
    assert len(body["pending_approvals"]) == 1
    row = body["pending_approvals"][0]
    assert row["title"] == "Send report"
    assert row["action"] == "send"
    assert row["payload"]["to"] == "boss@co.com"
