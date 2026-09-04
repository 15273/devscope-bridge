from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from devscope_bridge.main import app
import devscope_bridge.agy_session_index as index
import devscope_bridge.session_store as store


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "SESSIONS_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(store, "BRIDGE_DIR", tmp_path)
    monkeypatch.setattr(store, "BRIDGE_TRANSCRIPTS_DIR", tmp_path / "chat-transcripts")
    monkeypatch.setattr(store, "DEFAULT_CWD", str(tmp_path))
    cli = tmp_path / "cli"
    ide = tmp_path / "ide"
    (cli / "conversations").mkdir(parents=True)
    (cli / "history.jsonl").write_text(
        '{"conversationId":"aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",'
        '"display":"CLI one","workspace":"%s","timestamp":"2026-09-01T10:00:00Z"}\n'
        % tmp_path
    )
    sid = "ffffffff-1111-2222-3333-444444444444"
    (ide / "conversations").mkdir(parents=True)
    (ide / "conversations" / f"{sid}.pb").write_bytes(b"x")
    brain = ide / "brain" / sid
    brain.mkdir(parents=True)
    (brain / "task.md").write_text("# IDE task\nnotes")
    monkeypatch.setattr(index, "default_cli_root", lambda: cli)
    monkeypatch.setattr(index, "default_ide_root", lambda: ide)
    return sid


@pytest.mark.asyncio
async def test_discover_and_seed_import(isolated, tmp_path):
    transport = ASGITransport(app=app)
    headers = {"Authorization": "Bearer test-token-abc123"}
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        resp = await client.get("/antigravity-sessions/discover", headers=headers)
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert {i["source"] for i in items} >= {"antigravity_cli", "antigravity_ide"}
        ide = next(i for i in items if i["source"] == "antigravity_ide")
        assert ide["can_resume"] is False
        assert ide["seed_summary"] is True

        seeded = await client.post(
            "/antigravity-sessions/import",
            json={"session_id": isolated, "source": "antigravity_ide"},
            headers=headers,
        )
        assert seeded.status_code == 201
        body = seeded.json()
        assert body["agent"] == "antigravity"
        assert body["origin"] == "antigravity_ide"
        assert body["session_id"] == ""
