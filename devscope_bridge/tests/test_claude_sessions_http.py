"""HTTP discover + import for local Claude sessions."""

from __future__ import annotations

import json
import os

import pytest
from httpx import ASGITransport, AsyncClient

from devscope_bridge.main import app
import devscope_bridge.claude_session_index as index
import devscope_bridge.session_store as store


def _cli_home(tmp_path):
    home = tmp_path / "claude"
    proj = home / "projects" / "-Users-demo-app"
    sid = "dddddddd-bbbb-cccc-dddd-eeeeeeeeeeee"
    (tmp_path / "app").mkdir()
    path = proj / f"{sid}.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "type": "user",
                "cwd": str(tmp_path / "app"),
                "timestamp": "2026-08-22T09:00:00+00:00",
                "message": {"role": "user", "content": "hello from disk"},
            }
        )
        + "\n"
        + json.dumps({"type": "custom-title", "customTitle": "Hello disk"})
        + "\n"
    )
    return home, sid


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "SESSIONS_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(store, "BRIDGE_DIR", tmp_path)
    monkeypatch.setattr(store, "DEFAULT_CWD", str(tmp_path))
    home, sid = _cli_home(tmp_path)
    monkeypatch.setattr(index, "default_claude_home", lambda: home)
    monkeypatch.setattr(index, "default_desktop_code_root", lambda: tmp_path / "no-code")
    monkeypatch.setattr(index, "default_desktop_local_root", lambda: tmp_path / "no-local")
    return sid


@pytest.mark.asyncio
async def test_discover_lists_cli_session(isolated):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        resp = await client.get(
            "/claude-sessions/discover",
            headers={"Authorization": "Bearer test-token-abc123"},
        )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["session_id"] == isolated
    assert items[0]["title"] == "Hello disk"
    assert items[0]["source"] == "claude_code"
    assert items[0]["can_resume"] is True
    assert items[0]["already_imported"] is False


@pytest.mark.asyncio
async def test_import_then_conflict(isolated, tmp_path):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        first = await client.post(
            "/claude-sessions/import",
            json={"session_id": isolated, "source": "claude_code"},
            headers={"Authorization": "Bearer test-token-abc123"},
        )
        assert first.status_code == 201
        body = first.json()
        assert body["name"] == "cc-dddddddd"
        assert body["session_id"] == isolated
        assert body["display_title"] == "Hello disk"
        assert body["origin"] == "claude_code"
        assert body["cwd"] == str(tmp_path / "app")

        second = await client.post(
            "/claude-sessions/import",
            json={"session_id": isolated, "source": "claude_code"},
            headers={"Authorization": "Bearer test-token-abc123"},
        )
        assert second.status_code == 409


@pytest.mark.asyncio
async def test_import_unknown_is_404():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        resp = await client.post(
            "/claude-sessions/import",
            json={"session_id": "ffffffff-ffff-ffff-ffff-ffffffffffff", "source": "claude_code"},
            headers={"Authorization": "Bearer test-token-abc123"},
        )
    assert resp.status_code == 404


def test_subscription_env_sets_config_dir(tmp_path, monkeypatch):
    from devscope_bridge.session_runtime import subscription_env

    monkeypatch.setattr(store, "SESSIONS_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(store, "BRIDGE_DIR", tmp_path)
    store.import_claude_session(
        session_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        source="desktop_local",
        cwd=str(tmp_path),
        display_title="Local",
        claude_config_dir=str(tmp_path / "isolated.claude"),
    )
    env = subscription_env("dl-aaaaaaaa")
    assert env["CLAUDE_CONFIG_DIR"] == str(tmp_path / "isolated.claude")
    assert env["DEVSCOPE_SESSION"] == "dl-aaaaaaaa"

    store.create_session_metadata("plain", "claude", str(tmp_path))
    plain = subscription_env("plain")
    assert "CLAUDE_CONFIG_DIR" not in plain or plain.get("CLAUDE_CONFIG_DIR") == os.environ.get(
        "CLAUDE_CONFIG_DIR"
    )


def test_transcript_path_uses_config_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "SESSIONS_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(store, "BRIDGE_DIR", tmp_path)
    sid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    isolated = tmp_path / "iso.claude"
    jsonl = isolated / "projects" / "-sandbox" / f"{sid}.jsonl"
    jsonl.parent.mkdir(parents=True)
    jsonl.write_text("{}\n")
    store.import_claude_session(
        session_id=sid,
        source="desktop_local",
        cwd=str(tmp_path),
        claude_config_dir=str(isolated),
    )
    assert store.transcript_path("dl-aaaaaaaa") == str(jsonl)
