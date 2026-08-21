import pytest
from fastapi import HTTPException
from devscope_bridge import browser_relay


class FakeWS:
    async def send_text(self, text):  # pragma: no cover - not reached in these tests
        pass


@pytest.fixture(autouse=True)
def clean_registry():
    browser_relay._active_ws.clear()
    yield
    browser_relay._active_ws.clear()


def test_resolve_falls_back_to_any_active_ws():
    browser_relay.register_ws("chat-main", FakeWS())
    assert browser_relay.resolve_requesting_session("worker-abc123") == "chat-main"


def test_resolve_prefers_exact_match():
    browser_relay.register_ws("chat-main", FakeWS())
    browser_relay.register_ws("worker-abc123", FakeWS())
    assert browser_relay.resolve_requesting_session("worker-abc123") == "worker-abc123"


def test_resolve_none_when_nothing_connected():
    with pytest.raises(HTTPException) as exc:
        browser_relay.resolve_requesting_session("worker-abc123")
    assert exc.value.status_code == 503
