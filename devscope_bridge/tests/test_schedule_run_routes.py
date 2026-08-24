# devscope_bridge/tests/test_schedule_run_routes.py
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from devscope_bridge import task_homes, task_store
from devscope_bridge.schedule_routes import router as schedule_router


@pytest.fixture
def client(tmp_path):
    task_store.set_db_path(tmp_path / "agent_tasks.db")
    task_store.init_db()
    task_homes.set_base_dir(tmp_path / "task_homes")
    app = FastAPI()
    app.include_router(schedule_router)
    yield TestClient(app)
    task_store.set_db_path(None)
    task_homes.set_base_dir(None)


def _make_schedule(title="Daily digest") -> int:
    return task_store.add_schedule(
        title=title,
        template={"title": title, "instruction": "do it", "recurrence": {"daily_at": "09:00"}},
        next_run_at="2099-01-01 09:00:00",
    )


def test_report_closes_run_and_appends_memory(client):
    sid = _make_schedule()
    tid = task_store.create_task(title="run", kind="worker_unit", schedule_id=sid)
    run_id = task_store.create_schedule_run(sid, tid)

    res = client.post(
        f"/schedules/{sid}/runs/report",
        json={
            "task_id": tid,
            "digest": "פרסמתי את הפוסט, הכל תקין",
            "artifacts": ["reports/2026-08-21.md"],
            "memory_note": "the composer selector changed to .editor-v2",
            "status": "success",
        },
    )
    assert res.status_code == 200
    assert res.json()["ok"] is True

    run = task_store.get_schedule_run(run_id)
    assert run["status"] == "success"
    assert run["digest_text"] == "פרסמתי את הפוסט, הכל תקין"
    assert run["artifacts"] == ["reports/2026-08-21.md"]
    assert run["finished_at"]

    assert "the composer selector changed to .editor-v2" in task_homes.read_memory(sid)


def test_report_unknown_task_404(client):
    sid = _make_schedule()
    res = client.post(
        f"/schedules/{sid}/runs/report",
        json={"task_id": "nope", "digest": "x"},
    )
    assert res.status_code == 404


def test_report_already_closed_is_ok(client):
    sid = _make_schedule()
    tid = task_store.create_task(title="run", kind="worker_unit", schedule_id=sid)
    run_id = task_store.create_schedule_run(sid, tid)
    task_store.finish_schedule_run(run_id, status="failed", digest_text="died")

    res = client.post(
        f"/schedules/{sid}/runs/report",
        json={"task_id": tid, "digest": "late report"},
    )
    assert res.status_code == 200
    assert res.json().get("already_closed") is True
    assert task_store.get_schedule_run(run_id)["status"] == "failed"


def test_list_runs_newest_first(client):
    sid = _make_schedule()
    t1 = task_store.create_task(title="r1", kind="worker_unit", schedule_id=sid)
    t2 = task_store.create_task(title="r2", kind="worker_unit", schedule_id=sid)
    task_store.create_schedule_run(sid, t1)
    task_store.create_schedule_run(sid, t2)

    res = client.get(f"/schedules/{sid}/runs")
    assert res.status_code == 200
    runs = res.json()["runs"]
    assert [r["task_id"] for r in runs] == [t2, t1]


def test_memory_get_put(client):
    sid = _make_schedule()
    assert client.get(f"/schedules/{sid}/memory").json()["memory"] == ""

    put = client.put(f"/schedules/{sid}/memory", json={"content": "## notes\n- slow site\n"})
    assert put.status_code == 200
    assert client.get(f"/schedules/{sid}/memory").json()["memory"] == "## notes\n- slow site\n"


def test_reports_listing(client):
    sid = _make_schedule()
    rd = task_homes.reports_dir(sid)
    (rd / "2026-08-21.md").write_text("weekly report", encoding="utf-8")

    res = client.get(f"/schedules/{sid}/reports")
    assert res.status_code == 200
    reports = res.json()["reports"]
    assert len(reports) == 1
    assert reports[0]["name"] == "2026-08-21.md"


def test_run_now_sets_next_run_to_now(client):
    sid = _make_schedule()
    res = client.post(f"/schedules/{sid}/run")
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True

    sched = task_store.get_schedule(sid)
    assert sched["next_run_at"] <= datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def test_run_routes_404_on_missing_schedule(client):
    assert client.get("/schedules/999/runs").status_code == 404
    assert client.get("/schedules/999/memory").status_code == 404
    assert client.post("/schedules/999/run").status_code == 404
