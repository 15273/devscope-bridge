"""Tests for /meta/* routes."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from devscope_bridge.meta_ads_routes import router


def test_meta_health():
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    r = client.get("/meta/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "token_configured" in body["data"]
