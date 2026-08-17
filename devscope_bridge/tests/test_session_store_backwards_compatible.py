"""
test_session_store_backwards_compatible.py

Verify that old sessions.json entries (without agent/cwd fields) load
with the correct v1 defaults and do not cause any errors.
"""

import json
import pytest
from pathlib import Path
from unittest.mock import patch


def _write_old_sessions(tmp_path: Path, data: dict) -> Path:
    f = tmp_path / "sessions.json"
    f.write_text(json.dumps(data))
    return f


def test_old_entry_gets_default_agent_and_cwd(tmp_path, monkeypatch):
    """An entry that only has session_id/created_at/last_used loads with defaults."""
    import devscope_bridge.session_store as store

    old_entry = {
        "my-session": {
            "session_id": "abc123",
            "created_at": "2025-01-01 00:00",
            "last_used": "2025-01-02 00:00",
        }
    }
    sessions_file = _write_old_sessions(tmp_path, old_entry)
    monkeypatch.setattr(store, "SESSIONS_FILE", sessions_file)

    sessions = store.load_sessions()
    entry = sessions["my-session"]
    assert entry["agent"] == store.DEFAULT_AGENT
    assert entry["cwd"] == store.DEFAULT_CWD
    assert entry["session_id"] == "abc123"


def test_old_entry_via_get_session_returns_defaults(tmp_path, monkeypatch):
    """get_session() on an old entry returns defaults for missing fields."""
    import devscope_bridge.session_store as store

    old_entry = {
        "resume-me": {
            "session_id": "xyz",
            "created_at": "2025-06-01 10:00",
            "last_used": "2025-06-01 11:00",
        }
    }
    sessions_file = _write_old_sessions(tmp_path, old_entry)
    monkeypatch.setattr(store, "SESSIONS_FILE", sessions_file)

    entry = store.get_session("resume-me")
    assert entry is not None
    assert entry["agent"] == "claude"
    assert entry["cwd"] == store.DEFAULT_CWD


def test_new_entry_preserves_agent_and_cwd(tmp_path, monkeypatch):
    """Entries created with v1 agent/cwd are round-tripped correctly."""
    import devscope_bridge.session_store as store

    monkeypatch.setattr(store, "SESSIONS_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(store, "BRIDGE_DIR", tmp_path)

    store.create_session_metadata("proj", "cursor", "/tmp/myproject")
    entry = store.get_session("proj")
    assert entry["agent"] == "cursor"
    assert entry["cwd"] == "/tmp/myproject"


def test_missing_file_returns_empty_dict(tmp_path, monkeypatch):
    """load_sessions() returns {} when the file doesn't exist."""
    import devscope_bridge.session_store as store

    monkeypatch.setattr(store, "SESSIONS_FILE", tmp_path / "nonexistent.json")
    assert store.load_sessions() == {}


def test_corrupt_file_returns_empty_dict(tmp_path, monkeypatch):
    """load_sessions() returns {} when the file contains invalid JSON."""
    import devscope_bridge.session_store as store

    bad_file = tmp_path / "sessions.json"
    bad_file.write_text("{not valid json")
    monkeypatch.setattr(store, "SESSIONS_FILE", bad_file)
    assert store.load_sessions() == {}
