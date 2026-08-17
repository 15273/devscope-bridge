"""Session UUID isolation — one Claude conversation per DevScope chat."""

import pytest

from devscope_bridge import session_store


@pytest.fixture(autouse=True)
def isolated_sessions(tmp_path, monkeypatch):
    sessions_file = tmp_path / "sessions.json"
    monkeypatch.setattr(session_store, "BRIDGE_DIR", tmp_path)
    monkeypatch.setattr(session_store, "SESSIONS_FILE", sessions_file)
    yield


def test_upsert_session_refuses_cross_chat_uuid():
    session_store.save_sessions({
        "ability_check": {
            "session_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "last_used": "2026-07-09T10:00:00",
        },
    })
    session_store.upsert_session("atsIntegration", "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    sessions = session_store.load_sessions()
    assert sessions["ability_check"]["session_id"] == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    assert sessions.get("atsIntegration", {}).get("session_id", "") == ""


def test_repair_duplicate_session_ids_keeps_most_recent():
    shared = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    session_store.save_sessions({
        "ability_check": {
            "session_id": shared,
            "last_used": "2026-07-09T09:00:00",
        },
        "atsIntegration": {
            "session_id": shared,
            "last_used": "2026-07-09T11:00:00",
        },
    })
    cleared = session_store.repair_duplicate_session_ids()
    sessions = session_store.load_sessions()
    assert cleared == ["ability_check"]
    assert sessions["atsIntegration"]["session_id"] == shared
    assert sessions["ability_check"]["session_id"] == ""


def test_session_id_owner():
    session_store.save_sessions({
        "chat-a": {"session_id": "cccccccc-cccc-cccc-cccc-cccccccccccc"},
    })
    assert session_store.session_id_owner("cccccccc-cccc-cccc-cccc-cccccccccccc") == "chat-a"
    assert session_store.session_id_owner("unknown") is None
