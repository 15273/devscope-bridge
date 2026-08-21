import pytest
from devscope_bridge import orchestrator, task_store
from devscope_bridge.orchestrator_config import OrchestratorConfig


@pytest.fixture(autouse=True)
def tmp_db(tmp_path):
    task_store.set_db_path(tmp_path / "t.db")
    task_store.init_db()
    yield
    task_store.set_db_path(None)


class FakeRunner:
    def __init__(self):
        self.calls = []

    async def run_turn(self, name, prompt, **kw):
        self.calls.append((name, kw.get("agent"), kw.get("mode")))
        return True


@pytest.mark.asyncio
async def test_schedule_pass_dispatches_due_worker():
    task_store.add_schedule(
        title="t", template={"instruction": "go", "domain": "browser",
                             "recurrence": {"every_minutes": 30}},
        next_run_at="2000-01-01 00:00:00")
    runner = FakeRunner()
    n = await orchestrator.run_schedule_pass(runner, OrchestratorConfig(max_workers=3))
    assert n == 1
    assert runner.calls and runner.calls[0][0].startswith("worker-")


@pytest.mark.asyncio
async def test_schedule_pass_ignores_non_schedule_ready_tasks():
    tid = task_store.create_task(title="manual", kind="worker_unit", status="ready")
    runner = FakeRunner()
    n = await orchestrator.run_schedule_pass(runner, OrchestratorConfig(max_workers=3))
    assert n == 0 and runner.calls == []
    assert task_store.get_task(tid)["status"] == "ready"  # untouched; run_tick owns it
