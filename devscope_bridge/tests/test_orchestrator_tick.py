"""
test_orchestrator_tick.py — Tests for orchestrator tick logic and supporting machinery.

Task 5 (Plan 2): registry round-trip test for the long-running worker exemption.
Tasks 3/4 (Plan 2): run_tick tests with FakeRunner.
"""

import pytest

from devscope_bridge import session_reader, task_store, orchestrator
from devscope_bridge.orchestrator_config import OrchestratorConfig


def test_long_running_registry_roundtrip():
    session_reader.mark_long_running("worker-x")
    assert session_reader.is_long_running("worker-x") is True
    session_reader.clear_long_running("worker-x")
    assert session_reader.is_long_running("worker-x") is False


@pytest.fixture
def store(tmp_path):
    task_store.set_db_path(tmp_path / "agent_tasks.db")
    task_store.init_db()
    yield task_store
    task_store.set_db_path(None)


class FakeRunner:
    def __init__(self, on_turn=None):
        self.calls = []          # (name, prompt)
        self.on_turn = on_turn   # optional callback(name, prompt) to mutate the store

    async def run_turn(self, name, prompt, *, mode="act", agent="claude", timeout_s=600.0, **kwargs):
        self.calls.append((name, prompt))
        if self.on_turn:
            self.on_turn(name, prompt)
        return True


CFG = OrchestratorConfig(tick_seconds=720, max_workers=4,
                         domains=("browser", "research", "dev"))


@pytest.mark.asyncio
async def test_tick_skips_all_tiers_when_board_empty(store):
    runner = FakeRunner()
    await orchestrator.run_tick(runner, CFG, now="2026-06-08 12:00:00")
    assert runner.calls == []  # nothing to do → no Claude woken


@pytest.mark.asyncio
async def test_tick_wakes_mom_for_new_task(store):
    store.create_task(title="N", kind="mom_task", status="new")
    runner = FakeRunner()
    await orchestrator.run_tick(runner, CFG, now="2026-06-08 12:00:00")
    assert any(name == "mom" for name, _ in runner.calls)


@pytest.mark.asyncio
async def test_tick_wakes_domain_manager_for_assigned(store):
    store.create_task(title="A", kind="mom_task", domain="browser", status="assigned")
    runner = FakeRunner()
    await orchestrator.run_tick(runner, CFG, now="2026-06-08 12:00:00")
    assert any(name == "mgr-browser" for name, _ in runner.calls)


@pytest.mark.asyncio
async def test_tick_dispatches_ready_workers_up_to_cap(store):
    for i in range(6):
        store.create_task(title=f"W{i}", kind="worker_unit", status="ready",
                          instruction="do it")
    runner = FakeRunner(on_turn=lambda n, p: None)
    await orchestrator.run_tick(runner, CFG, now="2026-06-08 12:00:00")
    worker_calls = [n for n, _ in runner.calls if n.startswith("worker-")]
    assert len(worker_calls) == 4  # capped


@pytest.mark.asyncio
async def test_dispatched_worker_marked_in_progress(store):
    tid = store.create_task(title="W", kind="worker_unit", status="ready",
                            instruction="do it")
    runner = FakeRunner()
    await orchestrator.run_tick(runner, CFG, now="2026-06-08 12:00:00")
    assert store.get_task(tid)["status"] == "in_progress"


@pytest.mark.asyncio
async def test_dispatched_e2e_worker_gets_e2e_policy_in_prompt(store):
    from devscope_bridge import agent_policies as ap
    store.create_task(title="W", kind="worker_unit", status="ready", autonomy="e2e")
    runner = FakeRunner()
    await orchestrator.run_tick(runner, CFG, now="2026-06-08 12:00:00")
    worker_prompts = [p for name, p in runner.calls if name.startswith("worker-")]
    assert worker_prompts, "expected a worker to be dispatched"
    assert ap.WORKER_SAFETY_POLICY_E2E in worker_prompts[0]


@pytest.mark.asyncio
async def test_dispatched_guarded_worker_gets_guarded_policy(store):
    from devscope_bridge import agent_policies as ap
    store.create_task(title="W", kind="worker_unit", status="ready")  # default guarded
    runner = FakeRunner()
    await orchestrator.run_tick(runner, CFG, now="2026-06-08 12:00:00")
    worker_prompts = [p for name, p in runner.calls if name.startswith("worker-")]
    assert worker_prompts and ap.WORKER_SAFETY_POLICY in worker_prompts[0]


@pytest.mark.asyncio
async def test_reconcile_clears_stale_in_progress(store, monkeypatch):
    from devscope_bridge import orchestrator as orch

    tid = store.create_task(
        title="stuck", kind="worker_unit", status="in_progress",
    )
    store.update_task(tid, assignee_session="worker-stuck")
    # Backdate updated_at so reconcile fires immediately
    with store._connect() as conn:  # noqa: SLF001 — test-only
        conn.execute(
            "UPDATE tasks SET updated_at = '2026-06-08 10:00:00' WHERE id = ?",
            (tid,),
        )
        conn.commit()
    monkeypatch.setattr(
        "devscope_bridge.session_manager.is_turn_running",
        lambda _n: False,
    )
    cleared = orch.reconcile_stuck_workers(now="2026-06-08 12:00:00", stale_minutes=10)
    assert cleared == 1
    assert store.get_task(tid)["status"] == "failed"


@pytest.mark.asyncio
async def test_dispatch_timeout_marks_failed(store, monkeypatch):
    class TimeoutRunner:
        async def run_turn(self, name, prompt, *, mode="act", agent="claude",
                           timeout_s=600.0, **kwargs):
            return False

    tid = store.create_task(title="W", kind="worker_unit", status="ready", instruction="x")
    await orchestrator.run_tick(TimeoutRunner(), CFG, now="2026-06-08 12:00:00")
    assert store.get_task(tid)["status"] == "failed"


def _backdate(store, tid, ts="2026-06-08 10:00:00"):
    with store._connect() as conn:  # noqa: SLF001 — test-only
        conn.execute("UPDATE tasks SET updated_at = ? WHERE id = ?", (ts, tid))
        conn.commit()


def test_reconcile_stuck_parents_fails_idle_childless_parent(store):
    pid = store.create_task(title="zombie", kind="mom_task", status="in_progress")
    _backdate(store, pid)
    n = orchestrator.reconcile_stuck_parents(now="2026-06-08 14:00:00", stale_minutes=180)
    assert n == 1
    assert store.get_task(pid)["status"] == "failed"


def test_reconcile_stuck_parents_keeps_parent_with_live_child(store):
    pid = store.create_task(title="busy", kind="mom_task", status="in_progress")
    _backdate(store, pid)
    store.create_task(title="child", kind="worker_unit", parent_id=pid, status="ready")
    n = orchestrator.reconcile_stuck_parents(now="2026-06-08 14:00:00", stale_minutes=180)
    assert n == 0
    assert store.get_task(pid)["status"] == "in_progress"


def test_reconcile_stuck_parents_keeps_recent_parent(store):
    pid = store.create_task(title="fresh", kind="mom_task", status="in_progress")
    _backdate(store, pid, "2026-06-08 13:50:00")  # only 10m before 'now'
    n = orchestrator.reconcile_stuck_parents(now="2026-06-08 14:00:00", stale_minutes=180)
    assert n == 0
    assert store.get_task(pid)["status"] == "in_progress"


def test_reconcile_stuck_parents_ignores_worker_units(store):
    wid = store.create_task(title="w", kind="worker_unit", status="in_progress")
    _backdate(store, wid)
    assert orchestrator.reconcile_stuck_parents(now="2026-06-08 14:00:00", stale_minutes=180) == 0
