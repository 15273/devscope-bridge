# devscope_bridge/tests/test_task_store.py
import sqlite3
import pytest
from devscope_bridge import task_store


@pytest.fixture
def store(tmp_path):
    task_store.set_db_path(tmp_path / "agent_tasks.db")
    task_store.init_db()
    yield task_store
    task_store.set_db_path(None)  # reset to default


def test_init_db_creates_all_tables(store):
    with store._connect() as conn:
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
    assert {"tasks", "task_logs", "approvals", "schedules"} <= names


def test_init_db_is_idempotent(store):
    store.init_db()  # second call must not raise
    with store._connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    assert count == 0


def test_create_and_get_task(store):
    tid = store.create_task(title="Check inbox", detail="scan", kind="mom_task", source="chat")
    row = store.get_task(tid)
    assert row["title"] == "Check inbox"
    assert row["status"] == "new"
    assert row["kind"] == "mom_task"
    assert row["created_at"] and row["updated_at"]


def test_list_tasks_filters_by_status_and_domain(store):
    a = store.create_task(title="A", kind="worker_unit", domain="browser")
    store.create_task(title="B", kind="worker_unit", domain="research")
    store.update_task(a, status="ready", domain="browser")
    ready_browser = store.list_tasks(status="ready", domain="browser")
    assert [t["id"] for t in ready_browser] == [a]
    assert len(store.list_tasks()) == 2


def test_update_task_sets_fields_and_touches_updated_at(store):
    tid = store.create_task(title="A", kind="worker_unit")
    before = store.get_task(tid)["updated_at"]
    store.update_task(tid, status="in_progress", assignee_session="worker-1",
                      result_summary="started")
    row = store.get_task(tid)
    assert row["status"] == "in_progress"
    assert row["assignee_session"] == "worker-1"
    assert row["result_summary"] == "started"
    assert row["updated_at"] >= before


def test_update_task_rejects_unknown_status(store):
    tid = store.create_task(title="A", kind="worker_unit")
    with pytest.raises(ValueError):
        store.update_task(tid, status="banana")


def test_get_task_returns_none_when_missing(store):
    assert store.get_task("nope") is None


def test_add_and_list_logs_ordered(store):
    tid = store.create_task(title="A", kind="worker_unit")
    store.add_log(tid, actor="worker-1", message="started")
    store.add_log(tid, actor="worker-1", message="finished")
    logs = store.list_logs(tid)
    assert [l["message"] for l in logs] == ["started", "finished"]


def test_request_and_decide_approval(store):
    tid = store.create_task(title="Send email", kind="worker_unit")
    aid = store.request_approval(tid, action="send_email", payload={"to": "x@y.com"})
    pend = store.list_pending_approvals()
    assert len(pend) == 1 and pend[0]["id"] == aid
    store.decide_approval(aid, approved=True)
    assert store.list_pending_approvals() == []
    assert store.get_approval(aid)["status"] == "approved"


def test_due_schedules_materialise(store):
    store.add_schedule(title="Morning digest",
                       template={"title": "Daily digest", "kind": "mom_task"},
                       cron_expr="0 8 * * *", next_run_at="2000-01-01 08:00:00")
    due = store.due_schedules(now="2026-06-08 09:00:00")
    assert len(due) == 1 and due[0]["title"] == "Morning digest"
    # one not yet due
    store.add_schedule(title="Future", template={"title": "x", "kind": "mom_task"},
                       cron_expr="0 8 * * *", next_run_at="2999-01-01 08:00:00")
    assert len(store.due_schedules(now="2026-06-08 09:00:00")) == 1


def test_create_task_defaults_autonomy_to_guarded(store):
    tid = store.create_task(title="A", kind="mom_task")
    assert store.get_task(tid)["autonomy"] == "guarded"


def test_create_task_accepts_explicit_e2e(store):
    tid = store.create_task(title="A", kind="mom_task", autonomy="e2e")
    assert store.get_task(tid)["autonomy"] == "e2e"


def test_worker_unit_inherits_autonomy_from_parent(store):
    parent = store.create_task(title="P", kind="mom_task", autonomy="e2e")
    child = store.create_task(title="C", kind="worker_unit", parent_id=parent)
    assert store.get_task(child)["autonomy"] == "e2e"


def test_explicit_child_autonomy_overrides_parent(store):
    parent = store.create_task(title="P", kind="mom_task", autonomy="e2e")
    child = store.create_task(title="C", kind="worker_unit",
                              parent_id=parent, autonomy="guarded")
    assert store.get_task(child)["autonomy"] == "guarded"


def test_create_task_rejects_unknown_autonomy(store):
    with pytest.raises(ValueError):
        store.create_task(title="A", kind="mom_task", autonomy="wild")


def test_migration_adds_autonomy_to_legacy_db(tmp_path):
    import sqlite3
    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE tasks (id TEXT PRIMARY KEY, parent_id TEXT, kind TEXT NOT NULL, "
        "title TEXT NOT NULL, detail TEXT, source TEXT, domain TEXT, priority INTEGER, "
        "status TEXT NOT NULL, assignee_session TEXT, instruction TEXT, "
        "result_summary TEXT, artifact_path TEXT, created_at TEXT NOT NULL, "
        "updated_at TEXT NOT NULL, scheduled_for TEXT)")
    conn.commit()
    conn.close()
    task_store.set_db_path(db)
    try:
        task_store.init_db()  # must add the column without raising
        tid = task_store.create_task(title="A", kind="mom_task")
        assert task_store.get_task(tid)["autonomy"] == "guarded"
    finally:
        task_store.set_db_path(None)
