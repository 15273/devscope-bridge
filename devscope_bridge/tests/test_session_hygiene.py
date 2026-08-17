# devscope_bridge/tests/test_session_hygiene.py
"""Tests for automatic session hygiene."""

import json

import pytest

from devscope_bridge import session_hygiene, session_store, task_store


@pytest.fixture
def hygiene_env(tmp_path, monkeypatch):
    task_store.set_db_path(tmp_path / "agent_tasks.db")
    task_store.init_db()
    sessions_path = tmp_path / "sessions.json"
    sessions_path.write_text(json.dumps({
        "mom": {"session_id": "abc", "last_used": "2026-06-01 10:00"},
        "mgr-research": {"session_id": "def", "last_used": "2026-06-01 10:00"},
        "worker-old": {"session_id": "w1", "last_used": "2026-01-01 10:00"},
        "worker-live": {"session_id": "w2", "last_used": "2026-06-24 10:00"},
    }))
    monkeypatch.setattr(session_store, "SESSIONS_FILE", sessions_path)
    monkeypatch.setattr(session_store, "BRIDGE_DIR", tmp_path)
    monkeypatch.setattr(session_hygiene, "TASKS_DB", tmp_path / "agent_tasks.db")
    yield
    task_store.set_db_path(None)


def test_trim_recovery_backlog(hygiene_env):
    for i in range(5):
        tid = task_store.create_task(
            title=f"R{i}", kind="worker_unit", source="ats_recovery", status="ready",
        )
        assert tid
    n = session_hygiene.trim_recovery_backlog(cap=2)
    assert n == 3
    ready = task_store.list_tasks(status="ready")
    assert len(ready) == 2
    cancelled = task_store.list_tasks(status="cancelled")
    assert len(cancelled) == 3


def test_prune_worker_sessions(hygiene_env):
    live_id = task_store.create_task(title="Live", kind="worker_unit", status="in_progress")
    session_store.upsert_session(f"worker-{live_id}", "live-sid")
    n = session_hygiene.prune_worker_sessions(max_sessions=1)
    assert n >= 1
    assert session_store.get_session("worker-old") is None
    assert session_store.get_session(f"worker-{live_id}") is not None


@pytest.mark.asyncio
async def test_reset_for_fresh_turn(hygiene_env, monkeypatch):
    killed: list[str] = []

    async def fake_kill(name: str) -> None:
        killed.append(name)

    monkeypatch.setattr(session_hygiene.session_manager, "is_turn_running", lambda _n: False)
    monkeypatch.setattr(session_hygiene.session_manager, "kill_session", fake_kill)
    ok = await session_hygiene.reset_for_fresh_turn("mom")
    assert ok is True
    assert session_store.get_session("mom")["session_id"] == ""
    assert "mom" in killed
