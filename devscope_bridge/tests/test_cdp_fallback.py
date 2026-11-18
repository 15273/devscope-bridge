"""Token-auth CDP fallback when no extension WebSocket is connected."""

import pytest
from httpx import ASGITransport, AsyncClient

from devscope_bridge.browser_cdp import pick_page_target
from devscope_bridge.main import app
from devscope_bridge.service_workers import DEFAULT_DEVSCOPE_EXTENSION_ID, pick_service_worker


def test_pick_page_skips_service_workers_and_devtools():
    targets = [
        {"id": "sw", "type": "service_worker", "url": "chrome-extension://abc/sw.js"},
        {"id": "dt", "type": "page", "url": "devtools://devtools/bundled/inspector.html"},
        {"id": "page-1", "type": "page", "url": "https://jobs.lever.co/x/apply", "title": "Apply"},
    ]
    page = pick_page_target(targets)
    assert page["id"] == "page-1"
    assert pick_page_target(targets, "page-1")["title"] == "Apply"
    assert pick_page_target(targets, "missing") is None


def test_pick_service_worker_not_index_zero_in_cdp_list():
    targets = [
        {"id": "0", "type": "service_worker", "url": "chrome-extension://nkeimhogjdpnpccoofpliimaahmaaome/thunk.js"},
        {
            "id": "ds",
            "type": "service_worker",
            "url": f"chrome-extension://{DEFAULT_DEVSCOPE_EXTENSION_ID}/service-worker-loader.js",
        },
    ]
    assert pick_service_worker(targets, DEFAULT_DEVSCOPE_EXTENSION_ID)["id"] == "ds"


@pytest.mark.asyncio
async def test_actions_uses_cdp_fallback_when_no_ws(monkeypatch):
    async def _fake(tool, args, profile_name=None):
        assert tool == "browser_list_tabs"
        assert profile_name == "qa"
        return {
            "ok": True,
            "data": {"tabs": [{"id": "t1", "url": "https://example.com", "title": "Ex", "profile": "qa"}]},
            "error": None,
            "via": "cdp",
            "profile": "qa",
        }

    monkeypatch.setattr("devscope_bridge.browser_cdp.run_cdp_action", _fake)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        resp = await client.post(
            "/actions",
            json={"tool": "browser_list_tabs", "args": {}, "profile": "qa"},
            headers={"Authorization": "Bearer test-token-abc123"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["via"] == "cdp"
    assert body["data"]["tabs"][0]["profile"] == "qa"


@pytest.mark.asyncio
async def test_actions_still_403_without_token_even_with_cdp(monkeypatch):
    async def _should_not_run(*a, **k):
        raise AssertionError("CDP fallback must not run without a token")

    monkeypatch.setattr("devscope_bridge.browser_cdp.run_cdp_action", _should_not_run)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        resp = await client.post("/actions", json={"tool": "browser_list_tabs", "args": {}})
    assert resp.status_code == 403
