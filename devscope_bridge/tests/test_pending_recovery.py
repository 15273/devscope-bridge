"""
test_pending_recovery.py — A2/contract 3: GET /sessions/{name}/pending returns
all unresolved interactive requests for a session, so a panel that was closed
or disconnected when a card arrived can recover it on reopen.

Coverage
--------
1. session_reader.get_pending_permissions returns the PermissionRequest-shaped
   dict for a stored pending entry, filtered by session.
2. get_awaiting_kind reflects the pending entry's kind, None once resolved.
3. GET /sessions/{name}/pending (real FastAPI app) round-trips: create pending
   permission -> fetch -> resolve (pop) -> fetch again -> empty.
"""

import pytest
from httpx import AsyncClient, ASGITransport

import devscope_bridge.session_reader as sr
from devscope_bridge.main import app


@pytest.fixture(autouse=True)
def clean_pending():
    sr._pending_permissions.clear()
    yield
    sr._pending_permissions.clear()


def test_get_pending_permissions_filters_by_session_and_shapes_frame():
    sr._pending_permissions["req-1"] = {
        "session": "sess-a", "kind": "plan", "title": "Plan ready",
        "description": "do the thing", "options": [{"id": "approve", "label": "Approve"}],
        "plan_file_path": "/tmp/plan.md", "questions": None,
        "tool_name": None, "tool_input": None, "created_at": 123.0,
    }
    sr._pending_permissions["req-2"] = {
        "session": "sess-b", "kind": "ask_user", "title": "Questions",
        "description": "", "options": [], "plan_file_path": None,
        "questions": [{"header": "h", "question": "q?"}],
        "tool_name": None, "tool_input": None, "created_at": 124.0,
    }

    pending_a = sr.get_pending_permissions("sess-a")
    assert len(pending_a) == 1
    assert pending_a[0]["request_id"] == "req-1"
    assert pending_a[0]["type"] == "permission_request"
    assert pending_a[0]["kind"] == "plan"
    assert pending_a[0]["plan_file_path"] == "/tmp/plan.md"

    pending_b = sr.get_pending_permissions("sess-b")
    assert len(pending_b) == 1
    assert pending_b[0]["questions"] == [{"header": "h", "question": "q?"}]

    assert sr.get_pending_permissions("sess-c") == []


def test_get_awaiting_kind_reflects_and_clears():
    assert sr.get_awaiting_kind("sess-x") is None
    sr._pending_permissions["req-x"] = {"session": "sess-x", "kind": "tool_blocked"}
    assert sr.get_awaiting_kind("sess-x") == "tool_blocked"
    sr._pending_permissions.pop("req-x")
    assert sr.get_awaiting_kind("sess-x") is None


@pytest.mark.asyncio
async def test_pending_endpoint_round_trip():
    sr._pending_permissions["req-ep"] = {
        "session": "ep-sess", "kind": "plan", "title": "Plan ready",
        "description": "d", "options": [], "plan_file_path": None,
        "questions": None, "tool_name": None, "tool_input": None,
        "created_at": 1.0,
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        headers = {"Authorization": "Bearer test-token-abc123"}
        resp = await client.get("/sessions/ep-sess/pending", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["pending"]) == 1
        assert body["pending"][0]["request_id"] == "req-ep"

        # Resolve it (as send_approval would — it pops the entry).
        sr._pending_permissions.pop("req-ep")

        resp2 = await client.get("/sessions/ep-sess/pending", headers=headers)
        assert resp2.status_code == 200
        assert resp2.json()["pending"] == []
