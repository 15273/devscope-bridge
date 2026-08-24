# Recurring Tasks as Employees — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild DevScope recurring tasks as chat-first "employees": per-task chat + memory + digests, reliable scheduled browser runs, working cursor routing, chief-agent sweep for routine questions.

**Architecture:** Evolve existing rails. Backend: SQLite `schedules` + new `schedule_runs` table, per-schedule home dirs (`~/.dev-bridge/task_homes/{id}/` with `MEMORY.md` + `reports/`), scheduled tasks materialise directly as `worker_unit` (skip MoM/domain triage), a fast 60s scheduler sub-loop inside the orchestrator loop, browser-relay WS fallback, chief-agent sweep answering routine `action='question'` approvals. Frontend: SchedulePanel becomes an employee list; ScheduleDetailPanel becomes a run-digest feed + steward chat; NewScheduleModal is deleted in favor of chat-first setup with new commit MCP tools.

**Tech Stack:** Python 3.11 / FastAPI / SQLite / FastMCP (backend), React + TypeScript + Tailwind + vitest (extension).

**Spec:** `docs/superpowers/specs/2026-08-21-recurring-tasks-chat-design.md`

## Global Constraints

- Hebrew-first UI copy, `dir="rtl"` on new panels (match `SchedulePanel.tsx`).
- Timestamps: `"%Y-%m-%d %H:%M:%S"` local time (`_TS_FMT`), matching task_store.
- All SQLite writes go through `task_store.py` (bridge is single writer); MCP servers call REST over loopback (pattern: `task_mcp_server._call`).
- Additive column migrations only (pattern: `task_store._migrate`).
- Python tests: `pytest devscope_bridge/tests/`; extension tests: `cd extension && npx vitest run`.
- Commit after every task; message style matches repo (imperative, plain).
- New backend modules must not import `session_manager` from pure-logic modules (see `orchestrator_core.py` docstring).

---

## Phase 1 — Reliability core (backend)

### Task 1: `schedule_runs` table + store helpers

**Files:**
- Modify: `devscope_bridge/task_store.py` (schema `:62-78`, `_migrate` `:114`, helpers near `:368-475`)
- Test: `devscope_bridge/tests/test_schedule_runs.py` (create)

**Interfaces (Produces):**
```python
task_store.create_schedule_run(schedule_id: int, task_id: str) -> int        # status='running', started_at=now
task_store.finish_schedule_run(run_id: int, *, status: str,                 # success|failed|waiting_user|answered_by_chief
    digest_text: str | None = None, question_text: str | None = None,
    question_importance: str | None = None, answered_by: str | None = None,
    answer_text: str | None = None, artifacts: list[str] | None = None) -> None
task_store.get_schedule_run(run_id: int) -> dict | None
task_store.get_run_for_task(task_id: str) -> dict | None                    # latest run row for a task
task_store.list_schedule_runs(schedule_id: int, limit: int = 50) -> list[dict]  # newest first
task_store.list_waiting_runs() -> list[dict]                                # status='waiting_user' across schedules
```

- [ ] **Step 1: Write failing tests**

```python
# devscope_bridge/tests/test_schedule_runs.py
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
```

- [ ] **Step 2: Run to verify fail** — `pytest devscope_bridge/tests/test_schedule_runs.py -v` → AttributeError (`create_schedule_run` missing).

- [ ] **Step 3: Implement**

Append to `_SCHEMA` (before the index lines):

```sql
CREATE TABLE IF NOT EXISTS schedule_runs (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  schedule_id   INTEGER NOT NULL,
  task_id       TEXT NOT NULL,
  started_at    TEXT NOT NULL,
  finished_at   TEXT,
  status        TEXT NOT NULL DEFAULT 'running',  -- running|success|failed|waiting_user|answered_by_chief
  digest_text   TEXT,
  question_text TEXT,
  question_importance TEXT,                       -- routine | important
  answered_by   TEXT,
  answer_text   TEXT,
  artifacts_json TEXT,
  log_session   TEXT
);
CREATE INDEX IF NOT EXISTS idx_schedule_runs_sched ON schedule_runs(schedule_id);
CREATE INDEX IF NOT EXISTS idx_schedule_runs_task ON schedule_runs(task_id);
```

Helpers (place after `touch_schedule_run`). `_run_row` parses `artifacts_json` → `artifacts` list. `create_schedule_run` sets `log_session=f"worker-{task_id}"`. `finish_schedule_run` builds a dynamic UPDATE like `update_schedule` does, always sets `finished_at=_now_str()` unless status stays `running`. `list_waiting_runs` filters `status='waiting_user'`. `get_run_for_task` orders by id DESC LIMIT 1.

- [ ] **Step 4: Run tests → PASS.** Also run full suite: `pytest devscope_bridge/tests/ -x -q`.
- [ ] **Step 5: Commit** — `git commit -m "Add schedule_runs table and store helpers"`

### Task 2: Drift-free `_next_run_at` + `weekly_at`

**Files:**
- Modify: `devscope_bridge/orchestrator_core.py:152-163`, `:183-212`
- Test: `devscope_bridge/tests/test_next_run.py` (create)

**Interfaces (Produces):** `_next_run_at(recurrence: dict, now: str, *, anchor: str | None = None) -> str` — `anchor` is the schedule's previous `next_run_at` (the *scheduled* time); intervals advance from the anchor, not from tick time, so `daily_at 09:00` stays 09:00 even when the tick fires 09:07. New shape `{"weekly_at": {"day": 0-6, "time": "HH:MM"}}` (0=Monday, matching `datetime.weekday()`).

- [ ] **Step 1: Write failing tests**

```python
# devscope_bridge/tests/test_next_run.py
from devscope_bridge.orchestrator_core import _next_run_at


def test_daily_at_no_drift():
    # Tick fired late at 09:07 for a 09:00 schedule → next is tomorrow 09:00 sharp.
    nxt = _next_run_at({"daily_at": "09:00"}, "2026-08-21 09:07:33",
                       anchor="2026-08-21 09:00:00")
    assert nxt == "2026-08-22 09:00:00"


def test_every_minutes_anchored():
    nxt = _next_run_at({"every_minutes": 30}, "2026-08-21 10:07:00",
                       anchor="2026-08-21 10:00:00")
    assert nxt == "2026-08-21 10:30:00"


def test_every_minutes_skips_missed_slots():
    # Bridge was down for 2h → next slot is in the future, not a backlog burst.
    nxt = _next_run_at({"every_minutes": 30}, "2026-08-21 12:05:00",
                       anchor="2026-08-21 10:00:00")
    assert nxt == "2026-08-21 12:30:00"


def test_weekly_at():
    # 2026-08-21 is a Friday (weekday 4). Next Monday 08:00 → 2026-08-24.
    nxt = _next_run_at({"weekly_at": {"day": 0, "time": "08:00"}}, "2026-08-21 10:00:00")
    assert nxt == "2026-08-24 08:00:00"


def test_missing_recurrence_defaults_hour():
    assert _next_run_at({}, "2026-08-21 10:00:00") == "2026-08-21 11:00:00"
```

- [ ] **Step 2: Run → FAIL** (`anchor` unexpected kwarg).
- [ ] **Step 3: Implement**

```python
def _next_run_at(recurrence: dict, now: str, *, anchor: str | None = None) -> str:
    base = datetime.strptime(now, _TS_FMT)
    anchor_dt = None
    if anchor:
        try:
            anchor_dt = datetime.strptime(anchor, _TS_FMT)
        except ValueError:
            anchor_dt = None
    if "every_minutes" in recurrence:
        step = timedelta(minutes=int(recurrence["every_minutes"]))
        nxt = (anchor_dt or base) + step
        while nxt <= base:          # skip slots missed while the bridge was down
            nxt += step
        return nxt.strftime(_TS_FMT)
    if "daily_at" in recurrence:
        hh, mm = (int(x) for x in recurrence["daily_at"].split(":"))
        nxt = base.replace(hour=hh, minute=mm, second=0)
        while nxt <= base:
            nxt += timedelta(days=1)
        return nxt.strftime(_TS_FMT)
    if "weekly_at" in recurrence:
        spec = recurrence["weekly_at"]
        hh, mm = (int(x) for x in str(spec.get("time", "09:00")).split(":"))
        target_day = int(spec.get("day", 0))
        nxt = base.replace(hour=hh, minute=mm, second=0)
        while nxt <= base or nxt.weekday() != target_day:
            nxt += timedelta(days=1)
        return nxt.strftime(_TS_FMT)
    return (base + timedelta(hours=1)).strftime(_TS_FMT)
```

In `materialise_due_schedules`, pass the anchor at both call sites:
`task_store.set_schedule_next_run(sched["id"], _next_run_at(recurrence, now, anchor=sched.get("next_run_at")))`.

- [ ] **Step 4: Run tests + full suite → PASS.**
- [ ] **Step 5: Commit** — `"Compute schedule next-run from the scheduled time, add weekly recurrence"`

### Task 3: Scheduled tasks materialise as direct worker_units + run records

**Files:**
- Modify: `devscope_bridge/orchestrator_core.py:183-212` (`materialise_due_schedules`)
- Modify: `devscope_bridge/task_routes.py` (done-transition hook near `:75`)
- Test: `devscope_bridge/tests/test_schedule_runs.py` (extend)

**Why:** Today a scheduled task is `kind='mom_task', status='new'` and crawls through MoM→domain→worker across up to 3 ticks. A schedule's instruction is already precise — materialise straight to `kind='worker_unit', status='ready'` so the next dispatch pass runs it. Also open a `schedule_runs` row at materialise time.

**Interfaces:** Consumes Task 1 helpers. Produces: every scheduled (non-builtin) task has kind `worker_unit`, status `ready`, and one `schedule_runs` row in `running`.

- [ ] **Step 1: Failing test** (append to `test_schedule_runs.py`)

```python
def test_materialise_creates_ready_worker_and_run_row():
    from devscope_bridge import orchestrator_core as oc
    sid = task_store.add_schedule(
        title="מחקר בוקר", template={"instruction": "do research", "domain": "research",
                                     "recurrence": {"daily_at": "09:00"}},
        next_run_at="2026-08-21 09:00:00")
    n = oc.materialise_due_schedules(now="2026-08-21 09:00:30")
    assert n == 1
    tasks = task_store.list_tasks(status="ready")
    assert len(tasks) == 1
    t = tasks[0]
    assert t["kind"] == "worker_unit" and t["schedule_id"] == sid
    runs = task_store.list_schedule_runs(sid)
    assert len(runs) == 1 and runs[0]["status"] == "running" and runs[0]["task_id"] == t["id"]
    sched = task_store.get_schedule(sid)
    assert sched["next_run_at"] == "2026-08-22 09:00:00"
```

- [ ] **Step 2: Run → FAIL** (kind is mom_task / no run row).
- [ ] **Step 3: Implement** — in `materialise_due_schedules`, for the non-builtin branch change `create_task(...)` to `kind="worker_unit"`, `status="ready"` (drop `tmpl.get("kind", ...)`), then `task_store.create_schedule_run(sched["id"], tid)`.

In `task_routes.py`, at the existing `touch_schedule_run` done-transition hook, also close the run row:

```python
run = task_store.get_run_for_task(task_id)
if run and run["status"] == "running":
    task_store.finish_schedule_run(
        run["id"], status="success",
        digest_text=task.get("result_summary") or None)
```

and mirror it on the failed transition with `status="failed"`. (Task 7 makes the agent write a *good* digest via MCP before this fallback fires; this hook only fills in when it didn't.)

- [ ] **Step 4: Run tests + full suite → PASS.**
- [ ] **Step 5: Commit** — `"Materialise scheduled tasks as ready worker units with run records"`

### Task 4: Fast scheduler cadence (60s sub-loop)

**Files:**
- Modify: `devscope_bridge/orchestrator.py:282-306` (`_loop`), add `run_schedule_pass`
- Test: `devscope_bridge/tests/test_schedule_pass.py` (create)

**Interfaces (Produces):** `async orchestrator.run_schedule_pass(runner, cfg) -> int` — materialise due schedules and dispatch any ready **schedule-born** worker_units (task has `schedule_id`), capacity-checked; returns dispatched count. `_loop` sleeps in `SCHEDULE_PASS_SECONDS = 60` slices, runs `run_schedule_pass` every slice, full `run_tick` only when `tick_seconds` has elapsed.

- [ ] **Step 1: Failing test**

```python
# devscope_bridge/tests/test_schedule_pass.py
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
```

(Confirm `pytest-asyncio` is configured — other async tests exist; if `asyncio_mode` is not `auto`, keep the `@pytest.mark.asyncio` markers.)

- [ ] **Step 2: Run → FAIL** (no `run_schedule_pass`).
- [ ] **Step 3: Implement** in `orchestrator.py`:

```python
SCHEDULE_PASS_SECONDS = 60


async def run_schedule_pass(runner, cfg: OrchestratorConfig, now: str | None = None) -> int:
    """Lightweight sub-tick: materialise due schedules and dispatch ONLY
    schedule-born ready workers. The heavy run_tick still owns triage/rollup."""
    oc.materialise_due_schedules(now=now)
    b = oc.collect()
    running = oc.running_worker_count(b)
    dispatched = 0
    for task in oc.select_ready_workers(b, running, cfg.max_workers):
        if not task.get("schedule_id"):
            continue
        await _dispatch_worker(runner, task)
        dispatched += 1
    return dispatched
```

Rework `_loop`'s tail: replace `await asyncio.sleep(settings.tick_seconds)` with an inner slice loop —

```python
        elapsed = 0
        while elapsed < settings.tick_seconds:
            slice_s = min(SCHEDULE_PASS_SECONDS, settings.tick_seconds - elapsed)
            await asyncio.sleep(slice_s)
            elapsed += slice_s
            if elapsed < settings.tick_seconds:
                try:
                    await run_schedule_pass(runner, cfg)
                except Exception:
                    logger.exception("schedule pass failed")
```

(`run_tick` at loop top still calls `materialise_due_schedules` — double-fire is impossible because materialisation advances `next_run_at` atomically per pass.)

Note: `_dispatch_worker` awaits the whole worker turn — a long browser run would stall subsequent passes. Wrap dispatches in `asyncio.create_task(...)` **inside `run_schedule_pass` only** if tests show it matters; otherwise leave synchronous (run_tick has the same behavior today). Decide in-code with a comment.

- [ ] **Step 4: Run tests + full suite → PASS.**
- [ ] **Step 5: Commit** — `"Run a 60s schedule pass between full orchestrator ticks"`

### Task 5: Browser relay fallback for panel-less worker sessions

**Files:**
- Modify: `devscope_bridge/browser_relay.py:374-386` (`post_action`)
- Test: `devscope_bridge/tests/test_browser_relay_fallback.py` (create)

- [ ] **Step 1: Failing test**

```python
# devscope_bridge/tests/test_browser_relay_fallback.py
import pytest
from fastapi import HTTPException
from devscope_bridge import browser_relay


class FakeWS:
    async def send_text(self, text):  # pragma: no cover - not reached in these tests
        pass


@pytest.fixture(autouse=True)
def clean_registry():
    browser_relay._active_ws.clear()
    yield
    browser_relay._active_ws.clear()


def test_resolve_falls_back_to_any_active_ws():
    browser_relay.register_ws("chat-main", FakeWS())
    assert browser_relay.resolve_requesting_session("worker-abc123") == "chat-main"


def test_resolve_prefers_exact_match():
    browser_relay.register_ws("chat-main", FakeWS())
    browser_relay.register_ws("worker-abc123", FakeWS())
    assert browser_relay.resolve_requesting_session("worker-abc123") == "worker-abc123"


def test_resolve_none_when_nothing_connected():
    with pytest.raises(HTTPException) as exc:
        browser_relay.resolve_requesting_session("worker-abc123")
    assert exc.value.status_code == 503
```

- [ ] **Step 2: Run → FAIL** (no `resolve_requesting_session`).
- [ ] **Step 3: Implement** — extract the resolution from `post_action`:

```python
def resolve_requesting_session(requested: str | None) -> str:
    """Resolve which WS session serves this action.

    Exact match wins; otherwise ANY active extension WS serves the request —
    scheduled worker-* sessions have no panel of their own, and per-tab profile
    routing in _target_session still redirects to the right profile afterwards.
    """
    requesting = requested or first_active_session()
    if requesting is not None and has_active_ws(requesting):
        return requesting
    fallback = first_active_session()
    if fallback is not None:
        return fallback
    raise HTTPException(
        status_code=503,
        detail=(
            f"Browser client not connected (session={requested!r}, connected=[]). "
            "Reload DevScope unpacked from extension/dist or open the side panel."
        ),
    )
```

`post_action` becomes: `requesting = resolve_requesting_session(body.session)` then continues unchanged.

- [ ] **Step 4: Run tests + full suite → PASS.**
- [ ] **Step 5: Commit** — `"Fall back to any live extension socket for panel-less browser actions"`

### Task 6: Honor the schedule's engine (cursor routing)

**Files:**
- Modify: `devscope_bridge/session_runner.py:38-58`
- Test: `devscope_bridge/tests/test_session_runner_agent.py` (create)

- [ ] **Step 1: Failing test**

```python
# devscope_bridge/tests/test_session_runner_agent.py
import pytest
from unittest.mock import AsyncMock, patch
from devscope_bridge import session_runner


@pytest.mark.asyncio
async def test_run_turn_updates_stored_agent(tmp_path):
    with patch.object(session_runner.session_store, "get_session",
                      return_value={"name": "worker-x", "agent": "claude"}), \
         patch.object(session_runner.session_store, "upsert_session") as upsert, \
         patch.object(session_runner.session_manager, "run_prompt", new=AsyncMock()), \
         patch.object(session_runner.BridgeSessionRunner, "_await_turn",
                      new=AsyncMock(return_value=True)):
        ok = await session_runner.BridgeSessionRunner().run_turn(
            "worker-x", "go", agent="cursor")
    assert ok
    upsert.assert_called_once_with("worker-x", agent="cursor")
```

(Adjust the `upsert_session` kwargs in the test to the real signature — read `session_store.upsert_session` at `session_store.py:138` first; if it requires more fields, patch a narrower helper you add instead: `session_store.set_session_agent(name, agent)` following the exact pattern of `set_session_model` at `:112`.)

- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement** — add `set_session_agent` to `session_store.py` (copy `set_session_model`, field `"agent"`). In `run_turn`, after the create-if-missing block:

```python
        else_branch:  # i.e. session existed
            stored = session_store.get_session(name) or {}
            if stored.get("agent") != agent:
                session_store.set_session_agent(name, agent)
```

(Concretely: replace the `if session_store.get_session(name) is None:` block with an if/else where the else compares and updates the agent.)

- [ ] **Step 4: Run tests + full suite → PASS.**
- [ ] **Step 5: Commit** — `"Honor the requested engine when dispatching orchestrator turns"`

---

## Phase 2 — Run lifecycle, memory, reports (backend)

### Task 7: `task_homes` module

**Files:**
- Create: `devscope_bridge/task_homes.py`
- Test: `devscope_bridge/tests/test_task_homes.py` (create)

**Interfaces (Produces):**
```python
task_homes.home_dir(schedule_id: int) -> Path          # ~/.dev-bridge/task_homes/{id}, mkdir -p
task_homes.read_memory(schedule_id: int) -> str        # "" if missing
task_homes.write_memory(schedule_id: int, content: str) -> None
task_homes.append_memory(schedule_id: int, note: str) -> None  # appends "- {note}\n" under today's date header
task_homes.reports_dir(schedule_id: int) -> Path
task_homes.list_reports(schedule_id: int) -> list[dict]  # [{name, path, size, mtime}] newest first
task_homes.set_base_dir(path: Path | None) -> None     # test override, like task_store.set_db_path
```

- [ ] **Step 1: Failing test**

```python
# devscope_bridge/tests/test_task_homes.py
from devscope_bridge import task_homes


def test_memory_roundtrip(tmp_path):
    task_homes.set_base_dir(tmp_path)
    try:
        assert task_homes.read_memory(7) == ""
        task_homes.write_memory(7, "# זיכרון\n- האתר איטי בבקרים\n")
        assert "האתר איטי" in task_homes.read_memory(7)
        task_homes.append_memory(7, "צריך להתחבר מחדש כל שבוע")
        assert "להתחבר מחדש" in task_homes.read_memory(7)
    finally:
        task_homes.set_base_dir(None)


def test_reports_listing(tmp_path):
    task_homes.set_base_dir(tmp_path)
    try:
        rd = task_homes.reports_dir(7)
        (rd / "daily.md").write_text("x", "utf-8")
        reports = task_homes.list_reports(7)
        assert reports[0]["name"] == "daily.md" and reports[0]["size"] == 1
    finally:
        task_homes.set_base_dir(None)
```

- [ ] **Step 2: Run → FAIL** (module missing).
- [ ] **Step 3: Implement** — plain module, `_BASE = Path.home() / ".dev-bridge" / "task_homes"` with override global; `append_memory` reads existing content, appends `\n## {date}\n` header when today's date (`%Y-%m-%d`) is not already the last header, then `- {note}\n`.
- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** — `"Add per-schedule task homes with memory and reports"`

### Task 8: Run-report + memory REST routes and MCP tools

**Files:**
- Modify: `devscope_bridge/schedule_routes.py`, `devscope_bridge/schedule_models.py`, `devscope_bridge/task_mcp_server.py`
- Test: `devscope_bridge/tests/test_schedule_run_routes.py` (create; use FastAPI TestClient — copy setup from the existing tests that instantiate the app, e.g. grep `TestClient` under `devscope_bridge/tests/`)

**Interfaces (Produces):**
- `GET /schedules/{id}/runs` → `{"runs": [...]}` (Task 1 rows, newest first)
- `POST /schedules/{id}/runs/report` body `{task_id, digest, artifacts?: [str], memory_note?: str, status?: "success"|"failed"}` → closes the task's `running` row with the agent-authored digest, appends `memory_note` via `task_homes.append_memory`.
- `GET /schedules/{id}/memory` → `{"memory": str}`; `PUT /schedules/{id}/memory` body `{content}`.
- `GET /schedules/{id}/reports` → `{"reports": [...]}` from `task_homes.list_reports`.
- `POST /schedules/{id}/run` → force-run: `set_schedule_next_run(id, _now)`, then the next 60s pass picks it up; returns `{"ok": True, "next_run_at": ...}`.
- MCP tools in `task_mcp_server.py` (same `_call` pattern):

```python
@mcp.tool()
async def schedule_run_report(schedule_id: int, task_id: str, digest: str,
                              artifacts: list[str] | None = None,
                              memory_note: str | None = None,
                              status: str = "success") -> dict[str, Any]:
    """MANDATORY at the end of every scheduled run: short Hebrew digest of what
    happened, artifact paths written under the task home, and optionally one
    memory note worth keeping for future runs."""
    return await _call("POST", f"/schedules/{schedule_id}/runs/report", json_body={
        "task_id": task_id, "digest": digest, "artifacts": artifacts or [],
        "memory_note": memory_note, "status": status})


@mcp.tool()
async def schedule_memory_read(schedule_id: int) -> dict[str, Any]:
    """Read this recurring task's persistent MEMORY.md."""
    return await _call("GET", f"/schedules/{schedule_id}/memory")


@mcp.tool()
async def schedule_memory_write(schedule_id: int, content: str) -> dict[str, Any]:
    """Rewrite this recurring task's persistent MEMORY.md (full replace)."""
    return await _call("PUT", f"/schedules/{schedule_id}/memory",
                       json_body={"content": content})
```

- [ ] **Step 1: Failing tests** — TestClient tests: report closes the run row and appends memory; `GET runs` returns it; `POST /{id}/run` sets `next_run_at <= now`.
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement** routes (+ `ScheduleRunReportBody` pydantic model in `schedule_models.py`). `report` route: find `get_run_for_task(task_id)`; 404 if none; ignore (200, `{"ok": True, "already_closed": True}`) if not `running` — the fallback in task_routes may have closed it first.
- [ ] **Step 4: Run tests + full suite → PASS.**
- [ ] **Step 5: Commit** — `"Add run report, memory, and run-now routes with MCP tools"`

### Task 9: Scheduled-run prompt: memory + autonomy policy + report contract

**Files:**
- Modify: `devscope_bridge/agent_policies.py:129-145` (`build_worker_prompt`), `devscope_bridge/orchestrator.py:215-249` (`_dispatch_worker`), `devscope_bridge/schedule_models.py` (template gains `autonomy_policy: str | None = None`)
- Test: `devscope_bridge/tests/test_worker_prompt_schedule.py` (create)

**Interfaces:** `build_worker_prompt(..., schedule_id=None, memory: str = "", autonomy_policy: str = "")`. `_dispatch_worker` loads memory + policy when `task["schedule_id"]` is set:

```python
    memory = policy = ""
    if task.get("schedule_id"):
        from devscope_bridge import task_homes
        memory = task_homes.read_memory(task["schedule_id"])
        sched = task_store.get_schedule(task["schedule_id"])
        policy = ((sched or {}).get("template") or {}).get("autonomy_policy") or ""
```

Prompt additions when `schedule_id` (extend the existing `schedule_note`):

```python
        schedule_note = (
            f"\n\nThis task is run #{'{'}...{'}'} of recurring schedule #{schedule_id}. "
            "Follow the Playbook; after success call schedule_playbook_update(schedule_id, patch) "
            "with improved selectors.\n"
            "MANDATORY FINISH: call schedule_run_report(schedule_id, task_id, digest, artifacts, "
            "memory_note) with a short HEBREW digest (2-4 sentences, written like a colleague "
            "reporting back), the paths of any files you wrote under the task home reports dir, "
            "and one memory note if you learned something durable. Write accumulating outputs "
            "into the task home reports directory.\n"
            "If you hit a decision the autonomy policy below does not allow you to take, call "
            "task_ask_user(task_id, question) and STOP — the question waits in the task's chat."
        )
        if autonomy_policy:
            schedule_note += f"\n\n## Autonomy policy (set by the user)\n{autonomy_policy}"
        if memory:
            schedule_note += f"\n\n## Task memory (MEMORY.md — read before acting)\n{memory}"
```

Also pass the task-home reports path into the prompt: `_dispatch_worker` includes a line `Task home reports dir: ~/.dev-bridge/task_homes/{sid}/reports` (use the real expanded path from `task_homes.reports_dir`).

- [ ] **Step 1: Failing test** — `build_worker_prompt("t1", "x", "inst", schedule_id=5, memory="- slow site", autonomy_policy="never post")` contains `schedule_run_report`, `never post`, and `slow site`; without `schedule_id` contains none of them.
- [ ] **Step 2: Run → FAIL.** **Step 3: Implement.** **Step 4: PASS + full suite.**
- [ ] **Step 5: Commit** — `"Inject task memory, autonomy policy, and report contract into scheduled runs"`

### Task 10: `waiting_user` propagation from question approvals

**Files:**
- Modify: `devscope_bridge/task_routes.py` (`request-approval` handler `:91`, `answer` handler `:113`)
- Test: `devscope_bridge/tests/test_schedule_question_flow.py` (create)

**Interfaces:** When a task with `schedule_id` requests `action='question'` → its `running` run row moves to `waiting_user` with `question_text` (importance defaults `"important"`; the agent may pass `payload={"importance": "routine"}`). When answered via `/tasks/{id}/answer` → run row returns to `running` and stamps `answered_by="user"`, `answer_text`. (Requeued task re-dispatches through the normal ready path; the run row keeps accumulating.)

- [ ] **Step 1: Failing test** — TestClient: create schedule + materialise (or insert task+run directly), POST `request-approval` with `{"action":"question","payload":{"question":"לפרסם?"}}`, assert run row `waiting_user` + question text; POST `answer` `{"answer":"כן"}`, assert row `running`, `answered_by == "user"`.
- [ ] **Step 2-4: FAIL → implement → PASS.** Implementation: in the request-approval handler after `employee_comms.notify_question`, and in `answer_question` after `decide_approval`, look up `task_store.get_run_for_task(task_id)` and update via a small store helper `task_store.set_run_question(run_id, question_text, importance)` / `task_store.set_run_answered(run_id, answered_by, answer_text)` (add both to task_store; `set_run_answered` sets status back to `'running'` and clears nothing else).
- [ ] **Step 5: Commit** — `"Track schedule-run questions and answers on the run record"`

---

## Phase 3 — Chief agent

### Task 11: Chief-agent sweep for routine questions

**Files:**
- Create: `devscope_bridge/chief_agent.py`
- Modify: `devscope_bridge/orchestrator.py` (`run_schedule_pass` calls the sweep)
- Test: `devscope_bridge/tests/test_chief_agent.py` (create)

**Interfaces (Produces):**
```python
# chief_agent.py
async def sweep(now: str | None = None) -> int:
    """For each waiting_user run: ask the verdict LLM; if routine, answer the
    task via the same path as POST /tasks/{id}/answer and mark the run
    answered_by='chief'. Returns answered count."""

async def _verdict(policy: str, question: str, memory: str) -> dict:
    """LLM call → {"important": bool, "answer": str}. Separated for mocking."""
```

`_verdict` implementation: subprocess one-shot exactly like the existing pattern in `whatsapp/cockpit_agent.py:_run_claude` (read that file first and reuse its helper if importable; otherwise `claude -p <prompt> --output-format json` with a strict JSON-only instruction). Prompt (Hebrew-tolerant):

```
You are the chief agent supervising recurring automated tasks.
A task paused on a question. Decide from ITS autonomy policy whether answering
is within the task's own authority (routine) or must wait for the human (important).
DEFAULT TO IMPORTANT when uncertain, and ALWAYS important for anything involving
money, purchases, deletion, publishing publicly, or production systems.
Respond ONLY with JSON: {"important": true|false, "answer": "<answer if routine, else empty>"}

## Autonomy policy
{policy}
## Task memory (context)
{memory}
## Question
{question}
```

`sweep` skips runs whose `question_importance == "important"`? — No: importance on the row is what the *worker* claimed; the chief re-judges everything except rows the user must see because the verdict said important — after a verdict of important, stamp `question_importance='important'` and skip it on later sweeps (only re-judge rows still `NULL`/`'routine'`-claimed and not yet judged; add a simple guard: only judge rows where `answered_by IS NULL AND question_importance != 'important'`).

Answering: reuse the answer flow — factor the body of `task_routes.answer_question` into `task_routes.apply_answer(task_id, answer, actor="user") -> dict` and call it from both the route and `chief_agent.sweep(actor="chief")`; then `task_store.set_run_answered(run_id, "chief", answer)` and `task_store.finish_schedule_run` is NOT called (run continues).

Wire into `orchestrator.run_schedule_pass`: after dispatch, `await chief_agent.sweep()` inside try/except.

- [ ] **Step 1: Failing tests** — mock `_verdict`: (a) routine → task instruction gains the answer, status requeued, run row `answered_by == "chief"`; (b) important → nothing changes except `question_importance == "important"`; (c) money keyword never even reaches auto-answer if verdict says important (covered by (b)).
- [ ] **Step 2-4: FAIL → implement → PASS + full suite.**
- [ ] **Step 5: Commit** — `"Add chief-agent sweep that answers routine schedule questions"`

---

## Phase 4 — Chat-first creation (backend + MCP)

### Task 12: Setup drafts per-session + meta setters + commit tool

**Files:**
- Modify: `devscope_bridge/schedule_setup.py`, `devscope_bridge/schedule_routes.py`, `devscope_bridge/schedule_models.py`, `devscope_bridge/task_mcp_server.py`
- Test: `devscope_bridge/tests/test_schedule_setup_commit.py` (create)

**Changes:**
1. **Kill the global active draft:** drop `_ACTIVE_FILE`/`load_active`/`clear_active`; drafts live only at `{draft_id}.json`; `GET /schedules/setup/active` is deleted (frontend stops using it in Task 14). `get_draft` reads the file directly. Add `find_draft_by_session(session_name)` (scan dir, small N).
2. **Relax `ScheduleSetupStartBody`:** only `title: str = "משימה חדשה"` required-ish; `goal`, `entry_url` optional (`""` default) — chat-first setup starts empty and fills in by conversation.
3. **Draft gains fields:** `recurrence: dict = {}`, `autonomy_policy: str | None`, plus existing agent/mode.
4. **New draft setter route + MCP tool:**
   - `POST /schedules/setup/drafts/{id}/meta` body `{title?, recurrence?, agent?, autonomy_policy?, entry_url?, goal?}` → merge into draft.
   - `POST /schedules/setup/drafts/{id}/commit` → validate (must have `instruction` or `goal`, and `recurrence` non-empty), then `task_store.add_schedule(title=..., template={kind, detail: goal, domain, instruction, autonomy: "guarded", autonomy_policy, agent, mode: runtime_mode, recurrence}, playbook=draft playbook, next_run_at=_next_run_at(recurrence, now))` — import `_next_run_at` from `orchestrator_core`. Marks draft `status="committed", schedule_id=sid`. Returns the enriched schedule.
   - MCP tools:

```python
@mcp.tool()
async def schedule_setup_set_meta(draft_id: str, title: str | None = None,
                                  recurrence: dict | None = None,
                                  agent: str | None = None,
                                  autonomy_policy: str | None = None,
                                  entry_url: str | None = None,
                                  goal: str | None = None) -> dict[str, Any]:
    """Set schedule metadata on the in-progress setup draft. recurrence is one of
    {"daily_at": "HH:MM"} | {"every_minutes": N} | {"weekly_at": {"day": 0-6, "time": "HH:MM"}}."""
    body = {k: v for k, v in dict(title=title, recurrence=recurrence, agent=agent,
            autonomy_policy=autonomy_policy, entry_url=entry_url, goal=goal).items()
            if v is not None}
    return await _call("POST", f"/schedules/setup/drafts/{draft_id}/meta", json_body=body)


@mcp.tool()
async def schedule_commit(draft_id: str) -> dict[str, Any]:
    """Create the recurring schedule from the completed setup draft. Call ONLY after
    the user explicitly confirms the summary in chat."""
    return await _call("POST", f"/schedules/setup/drafts/{draft_id}/commit")
```

5. **Rewrite `_SETUP_SYSTEM`** for the interview flow (Hebrew-speaking colleague tone): find out what/when/where/engine/autonomy boundaries conversationally, keep the draft updated via `schedule_setup_set_meta` + `schedule_setup_update` as facts land, summarize and get explicit confirmation, then `schedule_commit`. Keep the read-only-browser rule and the "don't submit/post/purchase during setup" rule verbatim.

- [ ] **Step 1: Failing tests** — TestClient: start setup (title only) → set meta (recurrence daily_at 09:00, autonomy_policy text) → set instruction → commit → schedule exists with correct template incl. `autonomy_policy`, `next_run_at` computed for tomorrow-or-today 09:00; commit without recurrence → 400.
- [ ] **Step 2-4: FAIL → implement → PASS + full suite.** (Search repo for remaining `load_active` / `setup/active` references — `grep -rn "setup/active\|load_active"` — and remove/adjust each.)
- [ ] **Step 5: Commit** — `"Make schedule setup per-session with meta setters and chat commit"`

---

## Phase 5 — Extension UI

For every task in this phase: before writing UI, invoke the `frontend-design` skill (per-task implementer must do this) and match existing Tailwind token classes (`text-fg`, `bg-surface-raised`, `border-line`, `text-signal`, `text-2xs` — see `SchedulePanel.tsx`). All new panels `dir="rtl"`, Hebrew copy, human tone (an employee talking, not a system log). After each task: `cd extension && npx tsc --noEmit && npx vitest run`.

### Task 13: bridge.ts API surface

**Files:**
- Modify: `extension/src/sidepanel/bridge.ts` (schedule section near `:885-961`)
- Test: `extension/src/sidepanel/utils/scheduleApi.test.ts` — only if bridge fns are pure-testable; otherwise typecheck suffices (bridge.ts is a thin fetch layer; follow its existing untested style).

**Interfaces (Produces):**
```ts
export interface ScheduleRun {
  id: number; schedule_id: number; task_id: string;
  started_at: string; finished_at: string | null;
  status: 'running' | 'success' | 'failed' | 'waiting_user' | 'answered_by_chief';
  digest_text: string | null; question_text: string | null;
  question_importance: string | null; answered_by: string | null;
  answer_text: string | null; artifacts: string[]; log_session: string | null;
}
export async function fetchScheduleRuns(id: number): Promise<ScheduleRun[]>
export async function runScheduleNow(id: number): Promise<void>          // POST /schedules/{id}/run
export async function fetchScheduleMemory(id: number): Promise<string>
export async function fetchScheduleReports(id: number): Promise<{name: string; path: string; size: number; mtime: string}[]>
export async function answerTask(taskId: string, answer: string): Promise<void>  // POST /tasks/{id}/answer
export async function setScheduleEnabled(id: number, enabled: boolean): Promise<void>  // PATCH
// deleteSchedule already exists at bridge.ts:961 — leave as-is, it gets a caller in Task 14.
```

Copy the fetch/auth pattern of the existing `fetchSchedules` / `deleteSchedule` functions exactly.

- [ ] **Step 1: Implement** the functions + types. **Step 2:** `npx tsc --noEmit` clean. **Step 3: Commit** — `"Add schedule runs, memory, and control calls to the bridge client"`

### Task 14: Employee list + task chat feed (replace ScheduleDetailPanel)

**Files:**
- Modify: `extension/src/sidepanel/components/SchedulePanel.tsx` (list redesign)
- Create: `extension/src/sidepanel/components/ScheduleChatPanel.tsx` (replaces detail panel usage; delete `ScheduleDetailPanel.tsx` after the playbook editor moves)
- Modify: `extension/src/sidepanel/components/TaskBoard.tsx:316,352` (wire props)
- Test: `extension/src/sidepanel/utils/scheduleFeed.test.ts` + Create: `extension/src/sidepanel/utils/scheduleFeed.ts`

**List (SchedulePanel):** each row = employee card: title, status dot (green `success` last run / red `failed` / amber `waiting_user` / gray never-ran — derive from latest run), "הריצה הבאה: …" (format relative: "היום 09:00" / "מחר 09:00" / date), last digest first line truncated. Header button text: "+ משימה חדשה" → now triggers chat-first setup (Task 15 wires it; this task keeps calling the existing `onNewSchedule` prop).

**Feed logic (pure, tested):**

```ts
// scheduleFeed.ts
import type { ScheduleRun } from '../bridge';

export interface FeedItem {
  kind: 'digest' | 'question' | 'chief_answer' | 'failure';
  runId: number; at: string; text: string;
  artifacts: string[]; logSession: string | null;
  answered?: { by: string; text: string };
}

export function buildFeed(runs: ScheduleRun[]): FeedItem[] { /* newest first:
  success   → digest   (text = digest_text ?? 'הריצה הסתיימה')
  failed    → failure  (text = digest_text ?? 'הריצה נכשלה')
  waiting_user → question (text = question_text)
  answered_by_chief / runs with answered_by → chief_answer appended after the digest item
  running   → digest with text 'רצה עכשיו…'
*/ }
```

- [ ] **Step 1: Failing vitest** for `buildFeed` mapping all five statuses (copy test style from `sessionSidebarGroups.test.ts`).
- [ ] **Step 2-3: FAIL → implement → PASS.**
- [ ] **Step 4: Build `ScheduleChatPanel.tsx`:** header (title, next run, פעולות: הרץ עכשיו / השהה·הפעל / מחק with confirm), scrollable feed of `FeedItem` bubbles (digest = plain bubble from the "employee"; question = highlighted card with inline answer input → `answerTask(taskId, answer)`; failure = red-tinted bubble; artifacts as chips), poll `fetchScheduleRuns` every 5s while mounted (match the 4s poll pattern the modal used). Below: composer input "דבר עם המשימה…" — on send, call the steward flow: reuse `onOpenSetupChat`-style prop lifted to `App.tsx` that opens/creates a chat session named `sched-steward-{id}` (purpose `'schedule_steward'`) seeded via a new bridge call `POST /schedules/{id}/steward` (add tiny backend route: create session metadata if missing + `run_prompt` with context block = template + MEMORY.md + last 5 digests + the user's message; mirror `schedule_setup.bootstrap_session` structure). Keep the playbook editor OUT of this panel — move the raw playbook JSON editing into a collapsed "מתקדם" drawer at the bottom (port from ScheduleDetailPanel), then delete `ScheduleDetailPanel.tsx`.
- [ ] **Step 5:** `npx tsc --noEmit && npx vitest run` clean; grep for dangling `ScheduleDetailPanel` imports.
- [ ] **Step 6: Commit** — `"Turn the schedules tab into an employee list with a per-task chat feed"`

### Task 15: Chat-first creation, modal deleted

**Files:**
- Delete: `extension/src/sidepanel/components/NewScheduleModal.tsx`
- Modify: `extension/src/sidepanel/components/TaskBoard.tsx` (remove modal render `:352` + state), `extension/src/sidepanel/App.tsx` (`openScheduleSetupChat` `:205` becomes the only creation path), `extension/src/sidepanel/integrations/scheduleSetup.ts` (drop `fetchActiveSetup`; add `startSetup(title?)` against the relaxed body)
- Create: `extension/src/sidepanel/components/ScheduleDraftCard.tsx`

**Flow:** "+ משימה חדשה" → `startSetup()` → open the returned `session_name` as a normal chat (existing `openScheduleSetupChat` path) → bootstrap fires the rewritten interview prompt. While a session with purpose `schedule_setup` is active, `Chat.tsx`'s parent renders `ScheduleDraftCard` pinned above the composer: polls `GET /schedules/setup/drafts/{id}` every 4s (draft id resolved from a new field returned by `startSetup` and stored on the session's UI state), shows title / recurrence (human-formatted: "כל יום ב-09:00") / engine / autonomy policy snippet / instruction state, with a subtle "עוד לא נקבע" for missing pieces. When draft `status === 'committed'`, card swaps to a success state with a button "לצ'אט של המשימה ←" that navigates to the Task-14 panel for the new `schedule_id`.
No commit button in the card — commitment happens in conversation (`schedule_commit` tool), the card only reflects state.

- [ ] **Step 1:** Implement `startSetup` + draft card + wiring; delete the modal; remove `fetchSetupDraft` polling hooks that lived in the modal; grep `NewScheduleModal|fetchActiveSetup|setup/active` → zero hits.
- [ ] **Step 2:** `npx tsc --noEmit && npx vitest run` clean.
- [ ] **Step 3: Commit** — `"Replace the schedule wizard with chat-first creation and a live draft card"`

### Task 16: Polish + E2E verification

**Files:** touched UI files from Tasks 13-15; no new modules.

- [ ] **Step 1:** frontend-design pass over the three new surfaces (employee list, chat feed, draft card): consistent spacing/typography with the rest of the sidepanel, empty states ("אין עדיין משימות חוזרות — צור אחת בשיחה"), loading skeletons, human Hebrew microcopy (the employee speaks first person: "סיימתי", "אני צריכה תשובה ממך").
- [ ] **Step 2:** Build the extension (`cd extension && npm run build` — check package.json for the exact script) and run the full backend suite.
- [ ] **Step 3: Manual E2E** (requires the user's Chrome + bridge running — if not available in this session, document the checklist in the PR/commit instead): create a task by chat → commit → force-run (`הרץ עכשיו`) → digest appears in feed → artifact chip present → ask flow: make the run ask a question → answer from feed → run resumes.
- [ ] **Step 4: Commit** — `"Polish the employee chat surfaces"`

---

## Self-review notes

- Spec coverage: data model (T1,7,8,10), creation chat (T12,15), per-task chat (T13,14), run pipeline incl. browser/cursor/timing fixes (T2-T6,T9), chief agent (T11), error handling (T3 fallback digest, T5 503-path, T11 fail-safe default-important), testing woven into every task.
- Deliberately dropped from spec scope during planning: none. Added beyond spec: direct-to-worker materialisation (T3) and the 60s sub-loop (T4) as the concrete mechanism for the spec's "timing fix"; steward bootstrap route folded into T14.
- Dead code cleanup (schedule_discover dead helpers, cron_expr) is intentionally NOT a task — touch only if a task collides with it.
