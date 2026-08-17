# devscope_bridge/tests/test_task_usage.py
"""Tests for per-task token usage tracking."""

import pytest

from devscope_bridge import session_reader, task_store, task_usage


@pytest.fixture
def store(tmp_path):
    task_store.set_db_path(tmp_path / "agent_tasks.db")
    task_store.init_db()
    yield task_store
    task_store.set_db_path(None)


def test_task_id_from_worker_session():
    assert task_usage.task_id_from_session("worker-abc123def456") == "abc123def456"
    assert task_usage.task_id_from_session("mgr-dev") is None
    assert task_usage.task_id_from_session("mom") is None


def test_add_task_usage_accumulates(store):
    tid = store.create_task(title="Browse", kind="worker_unit")
    store.add_task_usage(tid, input_tokens=1000, output_tokens=200, cost_usd=0.01, turn_count=1)
    store.add_task_usage(tid, input_tokens=500, output_tokens=100, cost_usd=0.005, turn_count=1)
    row = store.get_task(tid)
    assert row["usage_input_tokens"] == 1500
    assert row["usage_output_tokens"] == 300
    assert row["usage_turn_count"] == 2
    assert row["usage_cost_usd"] == pytest.approx(0.015)


def test_record_turn_usage_from_session_reader(store):
    tid = store.create_task(title="W", kind="worker_unit")
    session_reader.reset_session_usage(f"worker-{tid}")
    session_reader.accumulate_usage(
        f"worker-{tid}",
        {
            "usage": {
                "input_tokens": 800,
                "output_tokens": 120,
                "cache_read_input_tokens": 400,
            },
            "total_cost_usd": 0.02,
        },
    )
    row = store.get_task(tid)
    assert row["usage_input_tokens"] == 800
    assert row["usage_output_tokens"] == 120
    assert row["usage_cache_read_tokens"] == 400
    assert row["usage_cost_usd"] == pytest.approx(0.02)
    assert row["usage_turn_count"] == 1


def test_enrich_tasks_with_rollups(store):
    parent = store.create_task(title="Parent", kind="domain_task")
    child = store.create_task(title="Unit", kind="worker_unit", parent_id=parent)
    store.add_task_usage(child, input_tokens=1000, output_tokens=500, cost_usd=0.1, turn_count=2)
    tasks = task_usage.enrich_tasks_with_rollups([store.get_task(parent), store.get_task(child)])
    by_id = {t["id"]: t for t in tasks}
    assert by_id[parent]["usage_total_tokens"] == 1500
    assert by_id[parent]["usage_total_cost_usd"] == pytest.approx(0.1)
    assert by_id[child]["usage_total_tokens"] == 1500


def test_add_task_usage_unknown_task_is_noop(store):
    store.add_task_usage("missing-id", input_tokens=999, turn_count=1)
    assert store.get_task("missing-id") is None
