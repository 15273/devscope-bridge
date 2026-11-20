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
    import devscope_bridge.claude_cloud_sessions as cloud

    monkeypatch.setattr(store, "SESSIONS_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(store, "BRIDGE_DIR", tmp_path)
    monkeypatch.setattr(store, "DEFAULT_CWD", str(tmp_path))
    home, sid = _cli_home(tmp_path)
    monkeypatch.setattr(index, "default_claude_home", lambda: home)
    monkeypatch.setattr(index, "default_desktop_code_root", lambda: tmp_path / "no-code")
    monkeypatch.setattr(index, "default_desktop_local_root", lambda: tmp_path / "no-local")

    async def no_cloud(**_kw):
        return [], None

    monkeypatch.setattr(cloud, "fetch_cloud_sessions", no_cloud)
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


def _cloud_item(**overrides):
    from devscope_bridge.claude_session_index import SOURCE_CLAUDE_CLOUD, DiscoveredSession

    base = dict(
        session_id="session_01LIVE",
        title="Fix auth",
        cwd="/tmp/app",
        source=SOURCE_CLAUDE_CLOUD,
        last_used="2026-09-02T11:00:00Z",
        can_resume=True,
        already_imported=False,
        bridge_name=None,
    )
    base.update(overrides)
    return DiscoveredSession(**base)


@pytest.mark.asyncio
async def test_discover_includes_cloud_sessions(isolated, monkeypatch):
    import devscope_bridge.claude_cloud_sessions as cloud

    async def fake_fetch(**_kw):
        return [_cloud_item()], None

    monkeypatch.setattr(cloud, "fetch_cloud_sessions", fake_fetch)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        resp = await client.get(
            "/claude-sessions/discover",
            headers={"Authorization": "Bearer test-token-abc123"},
        )
    assert resp.status_code == 200
    body = resp.json()
    sources = {i["source"] for i in body["items"]}
    assert "claude_code" in sources
    assert "claude_cloud" in sources
    assert body.get("cloud_error") in (None, "")


@pytest.mark.asyncio
async def test_discover_keeps_local_when_cloud_fails(isolated, monkeypatch):
    import devscope_bridge.claude_cloud_sessions as cloud

    async def fake_fetch(**_kw):
        return [], "Sign in with claude.ai"

    monkeypatch.setattr(cloud, "fetch_cloud_sessions", fake_fetch)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        resp = await client.get(
            "/claude-sessions/discover",
            headers={"Authorization": "Bearer test-token-abc123"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["cloud_error"] == "Sign in with claude.ai"
    assert any(i["source"] == "claude_code" for i in body["items"])


@pytest.mark.asyncio
async def test_discover_keeps_local_when_cloud_times_out(isolated, monkeypatch):
    import asyncio
    import devscope_bridge.claude_cloud_sessions as cloud

    async def hang(**_kw):
        await asyncio.sleep(60)
        return [], None

    monkeypatch.setattr(cloud, "fetch_cloud_sessions", hang)
    monkeypatch.setattr(
        "devscope_bridge.session_http.CLOUD_DISCOVER_TIMEOUT_S", 0.05
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        resp = await client.get(
            "/claude-sessions/discover",
            headers={"Authorization": "Bearer test-token-abc123"},
            timeout=15,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert "ארכה יותר מדי" in (body.get("cloud_error") or "")
    assert any(i["source"] == "claude_code" for i in body["items"])


@pytest.mark.asyncio
async def test_import_cloud_teleports_then_persists(isolated, tmp_path, monkeypatch):
    import devscope_bridge.claude_cloud_sessions as cloud

    local_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

    async def fake_fetch_one(_sid):
        return {
            "id": "session_01LIVE",
            "title": "Fix auth",
            "config": {
                "sources": [
                    {"type": "git_repository", "url": "https://github.com/Acme/App.git"}
                ]
            },
        }

    def fake_prepare(_session, **_kw):
        return str(tmp_path / "app"), "session_01LIVE"

    def fake_teleport(session_id, cwd):
        assert session_id == "session_01LIVE"
        assert cwd == str(tmp_path / "app")
        return local_id

    monkeypatch.setattr(cloud, "fetch_cloud_session", fake_fetch_one)
    monkeypatch.setattr(cloud, "prepare_cloud_teleport", fake_prepare)
    monkeypatch.setattr(cloud, "run_teleport", fake_teleport)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        first = await client.post(
            "/claude-sessions/import",
            json={"session_id": "https://claude.ai/code/session_01LIVE", "source": "claude_cloud"},
            headers={"Authorization": "Bearer test-token-abc123"},
        )
        assert first.status_code == 201
        body = first.json()
        assert body["session_id"] == local_id
        assert body["origin"] == "claude_cloud"
        assert body["display_title"] == "Fix auth"
        assert body["cwd"] == str(tmp_path / "app")
        assert body["name"].startswith("cr-")
        stored = store.get_session(body["name"])
        assert stored is not None
        assert stored.get("origin_ref") == "session_01LIVE"
        assert store.session_ref_owner("session_01LIVE") == body["name"]

        again = await client.post(
            "/claude-sessions/import",
            json={"session_id": "session_01LIVE", "source": "claude_cloud"},
            headers={"Authorization": "Bearer test-token-abc123"},
        )
        assert again.status_code == 409


@pytest.mark.asyncio
async def test_import_cloud_dirty_git_is_422(isolated, monkeypatch):
    import devscope_bridge.claude_cloud_sessions as cloud
    from devscope_bridge.claude_cloud_sessions import CloudTeleportError

    async def fake_fetch_one(_sid):
        return {"id": "session_01LIVE", "title": "Fix auth"}

    def fake_prepare(_session, **_kw):
        raise CloudTeleportError("uncommitted changes in /tmp/app")

    monkeypatch.setattr(cloud, "fetch_cloud_session", fake_fetch_one)
    monkeypatch.setattr(cloud, "prepare_cloud_teleport", fake_prepare)
    monkeypatch.setattr(cloud, "run_teleport", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("teleport")))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        resp = await client.post(
            "/claude-sessions/import",
            json={"session_id": "session_01LIVE", "source": "claude_cloud"},
            headers={"Authorization": "Bearer test-token-abc123"},
        )
    assert resp.status_code == 422
    assert "uncommitted" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_import_cloud_unknown_is_404(isolated, monkeypatch):
    import devscope_bridge.claude_cloud_sessions as cloud
    from devscope_bridge.claude_cloud_sessions import CloudNotFoundError

    async def fake_fetch_one(_sid):
        raise CloudNotFoundError("Session not found")

    monkeypatch.setattr(cloud, "fetch_cloud_session", fake_fetch_one)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        resp = await client.post(
            "/claude-sessions/import",
            json={"session_id": "session_01MISSING", "source": "claude_cloud"},
            headers={"Authorization": "Bearer test-token-abc123"},
        )
    assert resp.status_code == 404
