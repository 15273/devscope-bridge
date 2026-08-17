"""
Cross-profile browser routing: the bridge lists tabs across every connected
Chrome profile and routes tab-targeted actions to the profile that owns the tab.
"""

import json

import pytest

from devscope_bridge import browser_relay as br


class FakeWS:
    """Minimal WS double that records every frame sent to it."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_text(self, text: str) -> None:
        self.sent.append(json.loads(text))


@pytest.fixture(autouse=True)
def _clean_relay_state():
    br._active_ws.clear()
    br._ws_profile.clear()
    br._tab_profile.clear()
    br._pending_actions.clear()
    br._action_session.clear()
    yield
    br._active_ws.clear()
    br._ws_profile.clear()
    br._tab_profile.clear()
    br._pending_actions.clear()
    br._action_session.clear()


def test_profile_of_falls_back_to_session_when_unregistered():
    br.register_ws("sess-a", FakeWS())
    assert br._profile_of("sess-a") == "session:sess-a"


def test_set_ws_profile_groups_sessions():
    br.register_ws("sess-a", FakeWS())
    br.register_ws("sess-b", FakeWS())
    br.set_ws_profile("sess-a", "prof-1", "Work")
    br.set_ws_profile("sess-b", "prof-1", "Work")  # same profile, two panels
    assert br._profile_of("sess-a") == "prof-1"
    assert br._one_session_per_profile() == {"prof-1": "sess-a"}


def test_one_session_per_distinct_profile():
    br.register_ws("sess-a", FakeWS())
    br.register_ws("sess-b", FakeWS())
    br.set_ws_profile("sess-a", "prof-1", "Work")
    br.set_ws_profile("sess-b", "prof-2", "Personal")
    chosen = br._one_session_per_profile()
    assert set(chosen.keys()) == {"prof-1", "prof-2"}


def test_target_session_routes_to_owning_profile():
    """A tab learned to live in another profile routes there, not to the requester."""
    br.register_ws("sess-a", FakeWS())
    br.register_ws("sess-b", FakeWS())
    br.set_ws_profile("sess-a", "prof-1", "Work")
    br.set_ws_profile("sess-b", "prof-2", "Personal")
    br._tab_profile[555] = "prof-2"  # tab 555 lives in Personal

    # Requesting session is in prof-1; target tab is in prof-2 → route to sess-b.
    target = br._target_session("browser_click", {"tab_id": 555}, "sess-a")
    assert target == "sess-b"


def test_target_session_stays_local_for_same_profile_tab():
    br.register_ws("sess-a", FakeWS())
    br.set_ws_profile("sess-a", "prof-1", "Work")
    br._tab_profile[10] = "prof-1"
    target = br._target_session("browser_click", {"tab_id": 10}, "sess-a")
    assert target == "sess-a"


def test_target_session_without_tab_id_uses_requester():
    br.register_ws("sess-a", FakeWS())
    br.set_ws_profile("sess-a", "prof-1", "Work")
    target = br._target_session("browser_snapshot", {}, "sess-a")
    assert target == "sess-a"


def test_learn_tab_profiles_records_ids():
    br._learn_tab_profiles([{"id": 1}, {"id": 2}, {"no_id": True}], "prof-9")
    assert br._tab_profile == {1: "prof-9", 2: "prof-9"}


def test_deregister_clears_profile():
    ws = FakeWS()
    br.register_ws("sess-a", ws)
    br.set_ws_profile("sess-a", "prof-1", "Work")
    br.deregister_ws("sess-a", ws)
    assert "sess-a" not in br._ws_profile
    assert "sess-a" not in br._active_ws


def test_deregister_ignores_stale_ws_after_fast_reconnect():
    """A1: deregistering an OLD ws must not evict a NEWER one already registered."""
    old_ws, new_ws = FakeWS(), FakeWS()
    br.register_ws("sess-a", old_ws)
    br.register_ws("sess-a", new_ws)  # fast reconnect replaces the entry
    br.deregister_ws("sess-a", old_ws)  # old connection's cleanup runs late
    assert br._active_ws.get("sess-a") is new_ws
