"""Regression tests for Claude process ownership and profile isolation."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import Mock, patch

import pytest

from devscope_bridge import session_manager as manager
from devscope_bridge import session_reader, session_store
from devscope_bridge.session_runtime import _ActiveSession


def _active(name: str, *, idle: bool) -> _ActiveSession:
    proc = Mock(pid=4242, returncode=None)
    done = asyncio.Event()
    if idle:
        done.set()
    return _ActiveSession(
        name=name,
        session_id="sid",
        proc=proc,
        out_queue=asyncio.Queue(),
        reader_task=Mock(),
        idle_task=Mock(),
        mode="act",
        model=None,
        turn_done=done,
    )


def test_interrupt_is_noop_for_idle_persistent_process(monkeypatch):
    active = _active("idle-claude", idle=True)
    monkeypatch.setitem(manager._sessions, "idle-claude", active)
    monkeypatch.setattr(manager, "_session_agent", lambda _name: "claude")

    with patch("devscope_bridge.session_manager.os.kill") as kill:
        assert manager.interrupt_session("idle-claude") is False
    kill.assert_not_called()
    assert active.turn_done.is_set()


def test_isolated_profile_never_falls_back_to_default_transcript(tmp_path, monkeypatch):
    sid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    default_jsonl = tmp_path / ".claude" / "projects" / "-default" / f"{sid}.jsonl"
    default_jsonl.parent.mkdir(parents=True)
    default_jsonl.write_text(json.dumps({"type": "assistant"}) + "\n")

    monkeypatch.setattr(session_store.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(session_store, "SESSIONS_FILE", tmp_path / "sessions.json")
    session_store.save_sessions({
        "isolated": {
            "session_id": sid,
            "agent": "claude",
            "cwd": str(tmp_path),
            "claude_config_dir": str(tmp_path / "isolated-profile"),
        }
    })

    assert session_store.transcript_path("isolated") is None


def test_process_cleanup_drops_only_ephemeral_reader_state():
    name = "cleanup-claude"
    session_reader._assistant_text_accum[name] = ["partial"]
    session_reader._current_tool[name] = "Bash"
    session_reader._last_output_at[name] = 123.0
    session_reader._stderr_tails[name] = session_reader.deque(["old failure"])
    session_reader._recent_events[name] = session_reader.deque([{"type": "assistant"}])
    session_reader._current_turn_ids[name] = "keep-turn-id"
    session_reader._session_usage[name] = {"turn_count": 2}

    session_reader.cleanup_runtime_state(name)

    assert name not in session_reader._assistant_text_accum
    assert name not in session_reader._current_tool
    assert name not in session_reader._last_output_at
    assert name not in session_reader._stderr_tails
    assert name not in session_reader._recent_events
    assert session_reader._current_turn_ids[name] == "keep-turn-id"
    assert session_reader._session_usage[name] == {"turn_count": 2}

