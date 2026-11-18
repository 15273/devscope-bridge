import pytest

from devscope_bridge.browser_profiles import (
    get_profile,
    load_profiles,
    parse_endpoints_spec,
)


def test_parse_named_and_bare_endpoints():
    parsed = parse_endpoints_spec("daily=127.0.0.1:9222,qa=127.0.0.1:9336")
    assert parsed == {"daily": "127.0.0.1:9222", "qa": "127.0.0.1:9336"}
    assert parse_endpoints_spec("127.0.0.1:9222") == {"daily": "127.0.0.1:9222"}


def test_rejects_non_loopback():
    with pytest.raises(ValueError, match="loopback"):
        parse_endpoints_spec("daily=8.8.8.8:9222")


def test_load_profiles_env_overrides_file_and_skips_default(tmp_path, monkeypatch):
    endpoints = tmp_path / "cdp-endpoints.json"
    endpoints.write_text('{"daily": "127.0.0.1:9222"}')
    profiles = load_profiles(
        env={"DEVSCOPE_CDP_ENDPOINTS": "qa=127.0.0.1:9336,daily=127.0.0.1:9223"},
        endpoints_file=endpoints,
        include_default_daily=False,
    )
    by_name = {p.name: p.cdp for p in profiles}
    assert by_name["daily"] == "127.0.0.1:9223"
    assert by_name["qa"] == "127.0.0.1:9336"
    assert get_profile("QA", profiles).cdp == "127.0.0.1:9336"


def test_default_daily_only_when_requested():
    assert load_profiles(env={}, endpoints_file=__import__("pathlib").Path("/nonexistent"), include_default_daily=False) == []
    daily = load_profiles(env={}, endpoints_file=__import__("pathlib").Path("/nonexistent"), include_default_daily=True)
    assert [p.name for p in daily] == ["daily"]
    assert daily[0].cdp == "127.0.0.1:9222"


def test_session_for_named_profile_matches_label():
    from devscope_bridge import browser_relay as br

    class FakeWS:
        async def send_text(self, text: str) -> None:
            return None

    br._active_ws.clear()
    br._ws_profile.clear()
    try:
        br.register_ws("sess-qa", FakeWS())
        br.set_ws_profile("sess-qa", "abcd", "qa")
        assert br._session_for_named_profile("QA") == "sess-qa"
        assert br._session_for_named_profile("daily") is None
    finally:
        br._active_ws.clear()
        br._ws_profile.clear()
