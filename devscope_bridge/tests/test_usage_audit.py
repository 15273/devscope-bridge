# devscope_bridge/tests/test_usage_audit.py
"""Tests for usage_audit — mocked ccusage, real sqlite fixture."""

import json

import pytest

from devscope_bridge import task_store, usage_audit


@pytest.fixture
def audit_env(tmp_path, monkeypatch):
    task_store.set_db_path(tmp_path / "agent_tasks.db")
    task_store.init_db()
    tid = task_store.create_task(title="W", kind="worker_unit", source="chat")
    task_store.add_task_usage(tid, input_tokens=1000, output_tokens=200, turn_count=1)
    monkeypatch.setattr(usage_audit, "TASKS_DB", tmp_path / "agent_tasks.db")
    monkeypatch.setattr(usage_audit, "SESSIONS_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(usage_audit, "BRIDGE_DIR", tmp_path)
    (tmp_path / "sessions.json").write_text(json.dumps({
        "sessions": {
            "mgr-research": {"session_id": "abc-123"},
            "worker-x": {"session_id": "def-456"},
        }
    }))
    (tmp_path / "orchestrator_config.json").write_text(json.dumps({"paused": False, "tick_seconds": 1200}))
    yield
    task_store.set_db_path(None)


def test_run_audit_merges_sources(audit_env, monkeypatch):
    monkeypatch.setattr(usage_audit, "_active_block", lambda: {
        "available": True, "total_tokens": 1_000_000, "cache_pct_of_total": 85,
    })
    monkeypatch.setattr(usage_audit, "_rank_sessions", lambda limit=25: [{
        "bridge_session": "mgr-research",
        "total_tokens": 500_000_000,
        "is_orchestrator": True,
    }])
    report = usage_audit.run_audit()
    assert report["task_backlog"]["available"] is True
    assert report["task_backlog"]["top_task_usage"]
    assert report["orchestrator"]["paused"] is False
    assert len(report["recommendations"]) > 0
    assert any(
        "Orchestrator manager sessions" in r or "cache tokens" in r
        for r in report["recommendations"]
    )


def test_task_id_from_session_worker():
    from devscope_bridge.task_usage import task_id_from_session
    assert task_id_from_session("worker-abc123def456") == "abc123def456"
