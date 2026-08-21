import pytest
from devscope_bridge import task_store


@pytest.fixture(autouse=True)
def tmp_db(tmp_path):
    task_store.set_db_path(tmp_path / "t.db")
    task_store.init_db()
    yield
    task_store.set_db_path(None)


def _mk_schedule() -> int:
    return task_store.add_schedule(title="research", template={"instruction": "x"})


def test_run_lifecycle_success():
    sid = _mk_schedule()
    tid = task_store.create_task(title="r", kind="worker_unit", schedule_id=sid)
    rid = task_store.create_schedule_run(sid, tid)
    row = task_store.get_schedule_run(rid)
    assert row["status"] == "running" and row["schedule_id"] == sid and row["task_id"] == tid
    task_store.finish_schedule_run(rid, status="success", digest_text="done, 3 findings",
                                   artifacts=["reports/a.md"])
    row = task_store.get_schedule_run(rid)
    assert row["status"] == "success"
    assert row["digest_text"] == "done, 3 findings"
    assert row["artifacts"] == ["reports/a.md"]
    assert row["finished_at"]


def test_waiting_runs_and_latest_for_task():
    sid = _mk_schedule()
    tid = task_store.create_task(title="r", kind="worker_unit", schedule_id=sid)
    rid = task_store.create_schedule_run(sid, tid)
    task_store.finish_schedule_run(rid, status="waiting_user",
                                   question_text="לפרסם את הפוסט?",
                                   question_importance="important")
    waiting = task_store.list_waiting_runs()
    assert [w["id"] for w in waiting] == [rid]
    assert task_store.get_run_for_task(tid)["id"] == rid
    runs = task_store.list_schedule_runs(sid)
    assert runs[0]["id"] == rid
