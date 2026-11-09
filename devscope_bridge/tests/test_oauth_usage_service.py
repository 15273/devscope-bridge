"""oauth_usage_service — credentials file fallback + CLAUDE_CONFIG_DIR."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from devscope_bridge import oauth_usage_service as ous


FAKE_TOKEN = "test-oauth-access-token-not-real"


def _write_creds(path: Path, token: str = FAKE_TOKEN) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"claudeAiOauth": {"accessToken": token, "refreshToken": "x"}}),
        encoding="utf-8",
    )


@pytest.fixture(autouse=True)
def _reset_cache(monkeypatch):
    monkeypatch.setattr(ous, "_cache", None)
    monkeypatch.setattr(ous, "_cache_at", 0.0)
    # Keychain path must not win over the fake file in these tests.
    async def _no_keychain() -> None:
        return None

    monkeypatch.setattr(ous, "_read_oauth_token_from_keychain", _no_keychain)


def test_credentials_path_default_home(tmp_path, monkeypatch):
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert ous._credentials_path() == tmp_path / ".claude" / ".credentials.json"


def test_credentials_path_honours_claude_config_dir(tmp_path, monkeypatch):
    cfg = tmp_path / "custom-claude"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    assert ous._credentials_path() == cfg / ".credentials.json"


def test_token_from_credentials_payload_happy():
    assert ous._token_from_credentials_payload(
        {"claudeAiOauth": {"accessToken": "abc"}}
    ) == "abc"


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"claudeAiOauth": {}},
        {"claudeAiOauth": {"accessToken": ""}},
        {"claudeAiOauth": {"accessToken": "   "}},
        {"claudeAiOauth": "nope"},
        "not-a-dict",
    ],
)
def test_token_from_credentials_payload_rejects(payload):
    assert ous._token_from_credentials_payload(payload) is None


def test_read_oauth_token_from_file(tmp_path, monkeypatch):
    creds = tmp_path / ".claude" / ".credentials.json"
    _write_creds(creds)
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert ous._read_oauth_token_from_file() == FAKE_TOKEN


def test_read_oauth_token_from_file_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert ous._read_oauth_token_from_file() is None


def test_read_oauth_token_from_file_via_config_dir(tmp_path, monkeypatch):
    cfg = tmp_path / "alt"
    _write_creds(cfg / ".credentials.json", token="from-config-dir")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    assert ous._read_oauth_token_from_file() == "from-config-dir"


@pytest.mark.asyncio
async def test_read_oauth_token_falls_back_to_file(tmp_path, monkeypatch):
    _write_creds(tmp_path / ".claude" / ".credentials.json")
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert await ous._read_oauth_token() == FAKE_TOKEN


@pytest.mark.asyncio
async def test_fetch_uses_file_token_and_does_not_log_it(tmp_path, monkeypatch, caplog):
    _write_creds(tmp_path / ".claude" / ".credentials.json")
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    captured: dict = {}

    class _FakeResp:
        status_code = 200

        def json(self):
            return {
                "five_hour": {"utilization": 10, "resets_at": "t"},
                "seven_day": {"utilization": 20, "resets_at": "t"},
                "extra_usage": {"is_enabled": False},
            }

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None):
            captured["url"] = url
            captured["auth"] = (headers or {}).get("Authorization", "")
            return _FakeResp()

    monkeypatch.setattr(ous.httpx, "AsyncClient", _FakeClient)
    with caplog.at_level("INFO"):
        result = await ous._fetch()

    assert result["available"] is True
    assert result["limits"]["five_hour"]["utilization"] == 10
    assert captured["auth"] == f"Bearer {FAKE_TOKEN}"
    # Never leak the token into logs.
    joined = "\n".join(r.getMessage() for r in caplog.records)
    assert FAKE_TOKEN not in joined
    assert "test-oauth-access-token" not in joined


@pytest.mark.asyncio
async def test_fetch_unavailable_when_no_credentials(tmp_path, monkeypatch):
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    result = await ous._fetch()
    assert result == {"available": False}
