"""
test_post_sessions_creates_metadata.py

Tests for POST /sessions:
- happy path creates metadata (201)
- 409 if name already exists
- 422 for invalid name regex
- 422 for unsupported agent
- 422 for non-absolute cwd
- 422 for non-existent cwd directory
"""

import json
import pytest
from httpx import AsyncClient, ASGITransport

from devscope_bridge.main import app
import devscope_bridge.session_store as store


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    """Redirect session store to a temp dir for each test."""
    monkeypatch.setattr(store, "SESSIONS_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(store, "BRIDGE_DIR", tmp_path)


@pytest.mark.asyncio
async def test_happy_path_creates_session(tmp_path):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        resp = await client.post(
            "/sessions",
            json={"name": "my-proj", "agent": "claude", "cwd": str(tmp_path)},
            headers={"Authorization": "Bearer test-token-abc123"},
        )
    assert resp.status_code == 201
    body = resp.json()
    assert body["agent"] == "claude"
    assert body["cwd"] == str(tmp_path)
    assert body["active"] is False

    # Confirm persisted
    entry = store.get_session("my-proj")
    assert entry is not None
    assert entry["agent"] == "claude"


@pytest.mark.asyncio
async def test_409_if_name_already_exists(tmp_path):
    store.create_session_metadata("dup-session", "claude", str(tmp_path))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        resp = await client.post(
            "/sessions",
            json={"name": "dup-session", "agent": "claude", "cwd": str(tmp_path)},
            headers={"Authorization": "Bearer test-token-abc123"},
        )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_422_invalid_session_name(tmp_path):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        resp = await client.post(
            "/sessions",
            json={"name": "bad name!", "agent": "claude", "cwd": str(tmp_path)},
            headers={"Authorization": "Bearer test-token-abc123"},
        )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_422_invalid_agent(tmp_path):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        resp = await client.post(
            "/sessions",
            json={"name": "ok-name", "agent": "gpt4", "cwd": str(tmp_path)},
            headers={"Authorization": "Bearer test-token-abc123"},
        )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_422_relative_cwd():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        resp = await client.post(
            "/sessions",
            json={"name": "ok-name", "agent": "claude", "cwd": "relative/path"},
            headers={"Authorization": "Bearer test-token-abc123"},
        )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_422_nonexistent_cwd():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        resp = await client.post(
            "/sessions",
            json={"name": "ok-name", "agent": "cursor", "cwd": "/this/path/does/not/exist/ever"},
            headers={"Authorization": "Bearer test-token-abc123"},
        )
    assert resp.status_code == 422
