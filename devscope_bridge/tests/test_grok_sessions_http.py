from __future__ import annotations

import json

import pytest
from httpx import ASGITransport, AsyncClient

from devscope_bridge.main import app
import devscope_bridge.grok_session_index as index
import devscope_bridge.session_store as store


def _home(tmp_path):
    home = tmp_path / "grok"
    sid = "01bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    sess = home / "sessions" / "%2Ftmp%2Fapp" / sid
    sess.mkdir(parents=True)
    (tmp_path / "app").mkdir()
    (sess / "summary.json").write_text(
        json.dumps(
            {
                "info": {"id": sid, "cwd": str(tmp_path / "app")},
                "generated_title": "Hello Grok",
                "last_active_at": "2026-09-10T12:00:00Z",
            }
        )
    )
    return home, sid


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "SESSIONS_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(store, "BRIDGE_DIR", tmp_path)
    monkeypatch.setattr(store, "DEFAULT_CWD", str(tmp_path))
    home, sid = _home(tmp_path)
    monkeypatch.setattr(index, "default_grok_home", lambda: home)
    return sid


@pytest.mark.asyncio
async def test_discover_and_import(isolated, tmp_path):
    transport = ASGITransport(app=app)
    headers = {"Authorization": "Bearer test-token-abc123"}
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        resp = await client.get("/grok-sessions/discover", headers=headers)
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["title"] == "Hello Grok"
        assert items[0]["agent"] == "grok"

        first = await client.post(
            "/grok-sessions/import",
            json={"session_id": isolated, "source": "grok"},
            headers=headers,
        )
        assert first.status_code == 201
        body = first.json()
        assert body["name"].startswith("gk-")
        assert body["agent"] == "grok"
        assert body["origin"] == "grok"

        bot = await client.post(
            "/grok-sessions/import",
            json={"session_id": isolated, "source": "grok_bot"},
            headers=headers,
        )
        assert bot.status_code == 409
