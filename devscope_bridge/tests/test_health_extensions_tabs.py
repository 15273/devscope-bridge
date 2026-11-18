"""GET /health lists connected extensions and cached tabs (no auth)."""

import pytest
from httpx import ASGITransport, AsyncClient

from devscope_bridge import browser_relay as br
from devscope_bridge.main import app


class FakeWS:
    async def send_text(self, text: str) -> None:
        return None


@pytest.fixture(autouse=True)
def _clean():
    br._active_ws.clear()
    br._ws_profile.clear()
    br._last_tabs.clear()
    yield
    br._active_ws.clear()
    br._ws_profile.clear()
    br._last_tabs.clear()


@pytest.mark.asyncio
async def test_health_includes_extensions_and_redacted_tabs(monkeypatch):
    br.register_ws("sess-daily", FakeWS())
    br.set_ws_profile("sess-daily", "prof-daily", "daily")
    br.remember_tabs([
        {
            "id": 11,
            "title": "Lever apply",
            "url": "https://jobs.lever.co/x/apply?token=sekrit",
            "profile_id": "prof-daily",
        }
    ])

    async def _no_cdp(extensions=None, timeout=0.4):
        return [
            {
                "name": "daily",
                "label": "daily",
                "cdp": "127.0.0.1:9222",
                "cdp_ok": False,
                "extension_connected": True,
                "tabs": 1,
            }
        ]

    monkeypatch.setattr("devscope_bridge.browser_cdp.profile_health_snapshot", _no_cdp)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        resp = await client.get("/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["extensions"] == [
        {"session": "sess-daily", "profile_id": "prof-daily", "profile_label": "daily"}
    ]
    assert body["tabs"][0]["title"] == "Lever apply"
    assert body["tabs"][0]["url"] == "https://jobs.lever.co/x/apply"
    assert "sekrit" not in resp.text
    assert body["profiles"][0]["name"] == "daily"
    assert body["profiles"][0]["extension_connected"] is True
    assert body["cdp_fallback"] is False


@pytest.mark.asyncio
async def test_health_empty_when_nothing_is_connected(monkeypatch):
    async def _none(extensions=None, timeout=0.4):
        return []

    monkeypatch.setattr("devscope_bridge.browser_cdp.profile_health_snapshot", _none)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        resp = await client.get("/health")
    body = resp.json()
    assert body["extensions"] == []
    assert body["tabs"] == []
    assert body["profiles"] == []
