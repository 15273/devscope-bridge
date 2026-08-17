"""
test_get_sessions_includes_agent_cwd.py

Verify that GET /sessions returns agent and cwd for all session entries,
including those loaded from legacy (v0) records that lack those fields.
"""

import pytest
from httpx import AsyncClient, ASGITransport

from devscope_bridge.main import app
import devscope_bridge.session_store as store


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "SESSIONS_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(store, "BRIDGE_DIR", tmp_path)


@pytest.mark.asyncio
async def test_list_sessions_returns_agent_and_cwd(tmp_path):
    store.create_session_metadata("backend", "claude", str(tmp_path))
    store.create_session_metadata("frontend", "cursor", "/tmp")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        resp = await client.get(
            "/sessions",
            headers={"Authorization": "Bearer test-token-abc123"},
        )

    assert resp.status_code == 200
    sessions = resp.json()["sessions"]
    assert "backend" in sessions
    assert sessions["backend"]["agent"] == "claude"
    assert sessions["backend"]["cwd"] == str(tmp_path)
    assert sessions["frontend"]["agent"] == "cursor"
    assert sessions["frontend"]["cwd"] == "/tmp"


@pytest.mark.asyncio
async def test_list_sessions_legacy_entry_has_defaults(tmp_path):
    """Old entries written without agent/cwd surface defaults in the API response."""
    import json

    old_data = {
        "old-session": {
            "session_id": "legacy-sid",
            "created_at": "2025-01-01 00:00",
            "last_used": "2025-01-02 00:00",
        }
    }
    (tmp_path / "sessions.json").write_text(json.dumps(old_data))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        resp = await client.get(
            "/sessions",
            headers={"Authorization": "Bearer test-token-abc123"},
        )

    assert resp.status_code == 200
    sessions = resp.json()["sessions"]
    entry = sessions["old-session"]
    assert entry["agent"] == store.DEFAULT_AGENT
    assert entry["cwd"] == store.DEFAULT_CWD


@pytest.mark.asyncio
async def test_list_sessions_empty_when_no_sessions():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        resp = await client.get(
            "/sessions",
            headers={"Authorization": "Bearer test-token-abc123"},
        )
    assert resp.status_code == 200
    assert resp.json()["sessions"] == {}
