"""HTTP discover + import for Codex sessions."""

from __future__ import annotations

import json

import pytest
from httpx import ASGITransport, AsyncClient

from devscope_bridge.main import app
import devscope_bridge.codex_session_index as index
import devscope_bridge.session_store as store


def _home(tmp_path):
    home = tmp_path / "codex"
    sid = "dddddddd-bbbb-cccc-dddd-eeeeeeeeeeee"
    (tmp_path / "app").mkdir()
    (home).mkdir()
    (home / "session_index.jsonl").write_text(
        json.dumps(
            {
                "id": sid,
                "thread_name": "Hello Codex",
                "cwd": str(tmp_path / "app"),
                "updated_at": "2026-09-03T09:00:00+00:00",
            }
        )
        + "\n"
    )
    return home, sid


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "SESSIONS_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(store, "BRIDGE_DIR", tmp_path)
    monkeypatch.setattr(store, "DEFAULT_CWD", str(tmp_path))
    home, sid = _home(tmp_path)
    monkeypatch.setattr(index, "default_codex_home", lambda: home)
    return sid


@pytest.mark.asyncio
async def test_discover_and_import(isolated, tmp_path):
    transport = ASGITransport(app=app)
    headers = {"Authorization": "Bearer test-token-abc123"}
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        resp = await client.get("/codex-sessions/discover", headers=headers)
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["title"] == "Hello Codex"
        assert items[0]["agent"] == "codex"

        first = await client.post(
            "/codex-sessions/import",
            json={"session_id": isolated, "source": "codex"},
            headers=headers,
        )
        assert first.status_code == 201
        body = first.json()
        assert body["name"] == "cx-dddddddd"
        assert body["agent"] == "codex"
        assert body["origin"] == "codex"

        again = await client.post(
            "/codex-sessions/import",
            json={"session_id": isolated, "source": "codex"},
            headers=headers,
        )
        assert again.status_code == 409


@pytest.mark.asyncio
async def test_create_codex_session(isolated, tmp_path):
    transport = ASGITransport(app=app)
    headers = {"Authorization": "Bearer test-token-abc123"}
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        resp = await client.post(
            "/sessions",
            json={"name": "cx-chat", "agent": "codex", "cwd": str(tmp_path)},
            headers=headers,
        )
    assert resp.status_code == 201
    assert resp.json()["agent"] == "codex"
