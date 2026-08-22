# devscope_bridge/tests/test_chief_agent.py
import pytest

from devscope_bridge import chief_agent, task_store


@pytest.fixture
def db(tmp_path):
    task_store.set_db_path(tmp_path / "agent_tasks.db")
    task_store.init_db()
    yield
    task_store.set_db_path(None)


def _waiting_run(*, importance="routine", policy="you may choose colors"):
    sid = task_store.add_schedule(
        title="Daily digest",
        template={"title": "Daily digest", "instruction": "do it",
                  "autonomy_policy": policy,
                  "recurrence": {"daily_at": "09:00"}},
        next_run_at="2099-01-01 09:00:00",
    )
    tid = task_store.create_task(title="run", kind="worker_unit",
                                 instruction="do it", schedule_id=sid)
    run_id = task_store.create_schedule_run(sid, tid)
    task_store.request_approval(tid, action="question",
                                payload={"question": "איזה צבע?"})
    task_store.update_task(tid, status="awaiting_approval")
    task_store.set_run_question(run_id, "איזה צבע?", importance=importance)
    return sid, tid, run_id


@pytest.mark.asyncio
async def test_routine_verdict_answers_and_requeues(db, monkeypatch):
    sid, tid, run_id = _waiting_run()

    async def fake_verdict(policy, question, memory):
        assert "you may choose colors" in policy
        return {"important": False, "answer": "כחול"}

    monkeypatch.setattr(chief_agent, "_verdict", fake_verdict)
    answered = await chief_agent.sweep()
    assert answered == 1

    task = task_store.get_task(tid)
    assert "כחול" in (task.get("instruction") or "")
    assert task["status"] == "ready"

    run = task_store.get_schedule_run(run_id)
    assert run["status"] == "running"
    assert run["answered_by"] == "chief"
    assert run["answer_text"] == "כחול"


@pytest.mark.asyncio
async def test_important_verdict_stamps_and_waits(db, monkeypatch):
    sid, tid, run_id = _waiting_run()

    async def fake_verdict(policy, question, memory):
        return {"important": True, "answer": ""}

    monkeypatch.setattr(chief_agent, "_verdict", fake_verdict)
    answered = await chief_agent.sweep()
    assert answered == 0

    run = task_store.get_schedule_run(run_id)
    assert run["status"] == "waiting_user"
    assert run["question_importance"] == "important"
    assert run["answered_by"] is None
    assert task_store.get_task(tid)["status"] == "awaiting_approval"


@pytest.mark.asyncio
async def test_worker_claimed_important_is_never_judged(db, monkeypatch):
    _waiting_run(importance="important")

    async def fake_verdict(policy, question, memory):  # pragma: no cover
        raise AssertionError("chief must not judge worker-claimed important questions")

    monkeypatch.setattr(chief_agent, "_verdict", fake_verdict)
    assert await chief_agent.sweep() == 0


@pytest.mark.asyncio
async def test_stamped_important_skipped_on_later_sweeps(db, monkeypatch):
    calls = []

    async def fake_verdict(policy, question, memory):
        calls.append(question)
        return {"important": True, "answer": ""}

    _waiting_run()
    monkeypatch.setattr(chief_agent, "_verdict", fake_verdict)
    await chief_agent.sweep()
    await chief_agent.sweep()
    assert len(calls) == 1
