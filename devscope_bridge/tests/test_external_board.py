# devscope_bridge/tests/test_external_board.py
"""Tests for the external-board sync engine (parser, idempotency, push hashing)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from devscope_bridge import external_board as eb
from devscope_bridge import task_links, task_store
from devscope_bridge.employee_config import EmployeeSettings


@pytest.fixture()
def temp_db(tmp_path):
    task_store.set_db_path(tmp_path / "tasks.db")
    task_store.init_db()
    yield
    task_store.set_db_path(None)


# ── _extract_json_array ───────────────────────────────────────────────────────

def test_extract_plain_array():
    text = '[{"id": "p1", "title": "Fix login", "status": "To Do", "url": "u"}]'
    items = eb._extract_json_array(text)
    assert items == [{"external_id": "p1", "title": "Fix login",
                      "status": "To Do", "url": "u", "detail": ""}]


def test_extract_fenced_and_prose_wrapped():
    text = 'Sure! Here are the items:\n```json\n[{"id": 5, "title": "T"}]\n```\nDone.'
    items = eb._extract_json_array(text)
    assert items[0]["external_id"] == "5"
    assert items[0]["title"] == "T"


def test_extract_garbage_returns_empty():
    assert eb._extract_json_array("I could not find that database.") == []
    assert eb._extract_json_array("[not json}") == []
    assert eb._extract_json_array('{"id": "x"}') == []


def test_extract_skips_malformed_entries():
    text = '[{"id": "a", "title": "ok"}, {"title": "missing id"}, "junk"]'
    items = eb._extract_json_array(text)
    assert [i["external_id"] for i in items] == ["a"]


# ── pull idempotency ─────────────────────────────────────────────────────────

def _items():
    return [
        {"external_id": "n1", "title": "Build X", "status": "To Do", "url": "https://n/1", "detail": ""},
        {"external_id": "n2", "title": "Done thing", "status": "Done", "url": "", "detail": ""},
    ]


def test_pull_creates_only_actionable_once(temp_db):
    created = eb._pull_new_items("notion", _items())
    assert created == 1  # 'Done thing' is not actionable
    created_again = eb._pull_new_items("notion", _items())
    assert created_again == 0  # idempotent via task_links PK
    tasks = task_store.list_tasks(status="new")
    assert len(tasks) == 1
    assert tasks[0]["source"] == "notion"
    link = task_links.get_by_task(tasks[0]["id"])
    assert link["external_id"] == "n1"


# ── push hashing ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_push_only_when_hash_changes(temp_db):
    tid = task_store.create_task(title="Build X", kind="mom_task", source="notion")
    task_links.upsert_link(tid, "notion", "n1")

    provider = eb.NotionProvider()
    cfg = EmployeeSettings(board_push_max_per_sync=5)
    with patch.object(provider, "push", new=AsyncMock(return_value=True)) as push:
        assert await eb._push_changed(provider, cfg) == 1   # first push
        assert await eb._push_changed(provider, cfg) == 0   # unchanged → skipped
        task_store.update_task(tid, status="done", result_summary="shipped")
        assert await eb._push_changed(provider, cfg) == 1   # status change → pushed
    status_arg = push.await_args.args[1]
    assert status_arg == "Done"


@pytest.mark.asyncio
async def test_run_sync_requires_configuration(temp_db):
    result = await eb.run_sync(EmployeeSettings())  # no database configured
    assert result["ok"] is False


# ── employee_config ──────────────────────────────────────────────────────────

def test_employee_config_defaults_off(tmp_path):
    from devscope_bridge import employee_config as ec
    with patch.object(ec, "_CONFIG_PATH", tmp_path / "employee.json"):
        cfg = ec.load()
        assert cfg.employee_enabled is False
        assert cfg.channels["panel"] is True
        patched = ec.patch({"employee_enabled": True, "channels": {"whatsapp": True}})
        assert patched.employee_enabled is True
        assert patched.channels["whatsapp"] is True
        assert patched.channels["panel"] is True  # merge, not replace
        assert ec.load().employee_enabled is True
