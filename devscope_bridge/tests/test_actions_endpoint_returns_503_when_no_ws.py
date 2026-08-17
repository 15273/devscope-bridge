"""
Test that POST /actions returns 503 when no Chrome extension WS is connected.
"""

import pytest
from httpx import AsyncClient, ASGITransport

from devscope_bridge.main import app


@pytest.mark.asyncio
async def test_returns_503_no_active_ws():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        resp = await client.post(
            "/actions",
            json={"tool": "browser_navigate", "args": {"url": "https://example.com"}},
            headers={"Authorization": "Bearer test-token-abc123"},
        )

    assert resp.status_code == 503
    assert "not connected" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_returns_403_without_token():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        resp = await client.post(
            "/actions",
            json={"tool": "browser_click", "args": {"selector": "#btn"}},
        )

    assert resp.status_code == 403
