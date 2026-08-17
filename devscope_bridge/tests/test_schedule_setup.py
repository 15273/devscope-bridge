"""Tests for schedule setup drafts and runtime agent resolution."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from devscope_bridge import schedule_setup as setup_svc
from devscope_bridge import task_store


def test_runtime_from_schedule_template():
    agent, mode = setup_svc.runtime_from_schedule_template({"agent": "cursor", "mode": "plan"})
    assert agent == "cursor"
    assert mode == "plan"


def test_runtime_for_task_reads_schedule(tmp_path, monkeypatch):
    monkeypatch.setattr(task_store, "_db_path", tmp_path / "tasks.db")
    task_store.init_db()
    sid = task_store.add_schedule(
        title="T",
        template={"title": "T", "agent": "cursor", "mode": "act", "recurrence": {"every_minutes": 60}},
        playbook={},
        next_run_at="2099-01-01 09:00:00",
    )
    tid = task_store.create_task(title="W", kind="worker_unit", schedule_id=sid, status="ready")
    agent, mode = setup_svc.runtime_for_task({"schedule_id": sid, "id": tid})
    assert agent == "cursor"
    assert mode == "act"


@pytest.mark.asyncio
async def test_start_setup_creates_setup_dir(tmp_path, monkeypatch):
    """First draft write must create schedule_setups/ (not only active.json parent)."""
    setup_dir = tmp_path / "schedule_setups"
    monkeypatch.setattr(setup_svc, "_SETUP_DIR", setup_dir)
    monkeypatch.setattr(setup_svc, "_ACTIVE_FILE", setup_dir / "active.json")
    assert not setup_dir.exists()
    with patch("devscope_bridge.schedule_setup.session_store.get_session", return_value=None):
        with patch("devscope_bridge.schedule_setup.session_store.create_session_metadata"):
            draft = await setup_svc.start_setup(
                title="Post",
                goal="Weekly LinkedIn post",
                entry_url="https://linkedin.com/feed/",
            )
    assert setup_dir.is_dir()
    assert (setup_dir / f"{draft['id']}.json").is_file()


@pytest.mark.asyncio
async def test_start_setup_creates_draft(tmp_path, monkeypatch):
    monkeypatch.setattr(setup_svc, "_SETUP_DIR", tmp_path)
    monkeypatch.setattr(setup_svc, "_ACTIVE_FILE", tmp_path / "active.json")
    with patch("devscope_bridge.schedule_setup.session_store.get_session", return_value=None):
        with patch("devscope_bridge.schedule_setup.session_store.create_session_metadata") as create:
            draft = await setup_svc.start_setup(
                title="Post",
                goal="Weekly LinkedIn post",
                entry_url="https://linkedin.com/feed/",
                agent="cursor",
                setup_mode="inspect",
            )
    assert draft["id"]
    assert draft["session_name"] == f"sched-setup-{draft['id']}"
    assert draft["agent"] == "cursor"
    create.assert_called_once()
    loaded = setup_svc.get_draft(draft["id"])
    assert loaded["goal"] == "Weekly LinkedIn post"


def test_update_playbook_merges(tmp_path, monkeypatch):
    monkeypatch.setattr(setup_svc, "_SETUP_DIR", tmp_path)
    monkeypatch.setattr(setup_svc, "_ACTIVE_FILE", tmp_path / "active.json")
    draft = {"id": "abc12345", "session_name": "sched-setup-abc12345", "playbook": {"workflow": ["a"]}, "status": "active"}
    setup_svc._persist_draft(draft)
    updated = setup_svc.update_playbook("abc12345", {"selectors": {"btn": ".x"}})
    assert updated["playbook"]["selectors"]["btn"] == ".x"
    assert updated["playbook"]["workflow"] == ["a"]
