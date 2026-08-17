"""
task_store.py — SQLite layer for the autonomous agent orchestrator.

Owns ~/.dev-bridge/agent_tasks.db. The dev_bridge process is the SOLE writer
(workers reach it through the /tasks HTTP routes, never SQLite directly), so we
keep a simple connection-per-call model with WAL for read concurrency.

Tables: tasks (hierarchical), task_logs (timeline), approvals, schedules.
"""

import json
import logging
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

BRIDGE_DIR = Path.home() / ".dev-bridge"
_DEFAULT_DB_PATH = BRIDGE_DIR / "agent_tasks.db"
_db_path: Path = _DEFAULT_DB_PATH

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
  id               TEXT PRIMARY KEY,
  parent_id        TEXT,
  kind             TEXT NOT NULL,        -- mom_task | domain_task | worker_unit
  title            TEXT NOT NULL,
  detail           TEXT,
  source           TEXT,                 -- chat | board | scheduled
  domain           TEXT,
  priority         INTEGER DEFAULT 0,
  status           TEXT NOT NULL,        -- new|assigned|ready|in_progress|
                                         -- awaiting_approval|approved|done|failed|cancelled
  assignee_session TEXT,
  instruction      TEXT,
  result_summary   TEXT,
  artifact_path    TEXT,
  created_at       TEXT NOT NULL,
  updated_at       TEXT NOT NULL,
  scheduled_for    TEXT,
  autonomy         TEXT NOT NULL DEFAULT 'guarded'   -- guarded | e2e
);
CREATE TABLE IF NOT EXISTS task_logs (
  id      INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id TEXT NOT NULL,
  ts      TEXT NOT NULL,
  actor   TEXT,
  message TEXT
);
CREATE TABLE IF NOT EXISTS approvals (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id      TEXT NOT NULL,
  action       TEXT,
  payload_json TEXT,
  status       TEXT NOT NULL,            -- pending | approved | rejected
  created_at   TEXT NOT NULL,
  decided_at   TEXT
);
CREATE TABLE IF NOT EXISTS schedules (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  title        TEXT NOT NULL,
  template_json TEXT NOT NULL,
  playbook_json TEXT,
  cron_expr    TEXT,
  next_run_at  TEXT,
  last_run_at  TEXT,
  last_task_id TEXT,
  enabled      INTEGER DEFAULT 1,
  updated_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_parent ON tasks(parent_id);
CREATE INDEX IF NOT EXISTS idx_tasks_domain ON tasks(domain);
CREATE INDEX IF NOT EXISTS idx_logs_task ON task_logs(task_id);
"""


def set_db_path(path: Path | None) -> None:
    """Override the DB path (tests). Pass None to reset to the default."""
    global _db_path
    _db_path = Path(path) if path is not None else _DEFAULT_DB_PATH


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _connect() -> sqlite3.Connection:
    _db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """Create all tables/indexes if missing, then run column migrations. Idempotent."""
    with _connect() as conn:
        conn.executescript(_SCHEMA)
        _migrate(conn)
    from devscope_bridge import task_links
    task_links.ensure_schema()
    logger.info("agent_tasks.db initialised at %s", _db_path)


def _migrate(conn: sqlite3.Connection) -> None:
    """Additive column migrations for pre-existing DBs. Each is a no-op if present."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(tasks)")}
    if "autonomy" not in cols:
        conn.execute("ALTER TABLE tasks ADD COLUMN autonomy TEXT DEFAULT 'guarded'")
    if "schedule_id" not in cols:
        conn.execute("ALTER TABLE tasks ADD COLUMN schedule_id INTEGER")
    if "project_path" not in cols:
        conn.execute("ALTER TABLE tasks ADD COLUMN project_path TEXT")
    for col, ddl in (
        ("usage_input_tokens", "ALTER TABLE tasks ADD COLUMN usage_input_tokens INTEGER NOT NULL DEFAULT 0"),
        ("usage_output_tokens", "ALTER TABLE tasks ADD COLUMN usage_output_tokens INTEGER NOT NULL DEFAULT 0"),
        ("usage_cache_read_tokens", "ALTER TABLE tasks ADD COLUMN usage_cache_read_tokens INTEGER NOT NULL DEFAULT 0"),
        ("usage_cache_write_tokens", "ALTER TABLE tasks ADD COLUMN usage_cache_write_tokens INTEGER NOT NULL DEFAULT 0"),
        ("usage_cost_usd", "ALTER TABLE tasks ADD COLUMN usage_cost_usd REAL NOT NULL DEFAULT 0"),
        ("usage_turn_count", "ALTER TABLE tasks ADD COLUMN usage_turn_count INTEGER NOT NULL DEFAULT 0"),
    ):
        if col not in cols:
            conn.execute(ddl)

    approval_cols = {r[1] for r in conn.execute("PRAGMA table_info(approvals)")}
    if "answer_text" not in approval_cols:
        conn.execute("ALTER TABLE approvals ADD COLUMN answer_text TEXT")

    sched_cols = {r[1] for r in conn.execute("PRAGMA table_info(schedules)")}
    for col, ddl in (
        ("playbook_json", "ALTER TABLE schedules ADD COLUMN playbook_json TEXT"),
        ("last_run_at", "ALTER TABLE schedules ADD COLUMN last_run_at TEXT"),
        ("last_task_id", "ALTER TABLE schedules ADD COLUMN last_task_id TEXT"),
        ("updated_at", "ALTER TABLE schedules ADD COLUMN updated_at TEXT"),
    ):
        if col not in sched_cols:
            conn.execute(ddl)


VALID_STATUSES = {
    "new", "assigned", "ready", "in_progress",
    "awaiting_approval", "approved", "done", "failed", "cancelled",
}
VALID_KINDS = {"mom_task", "domain_task", "worker_unit"}
VALID_AUTONOMY = {"guarded", "e2e"}


def create_task(
    *,
    title: str,
    kind: str,
    detail: str | None = None,
    source: str | None = None,
    domain: str | None = None,
    parent_id: str | None = None,
    priority: int = 0,
    instruction: str | None = None,
    scheduled_for: str | None = None,
    autonomy: str | None = None,
    status: str = "new",
    schedule_id: int | None = None,
    project_path: str | None = None,
) -> str:
    """Insert a task and return its id."""
    if kind not in VALID_KINDS:
        raise ValueError(f"invalid kind: {kind!r}")
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid status: {status!r}")
    if parent_id is not None and (autonomy is None or project_path is None):
        parent = get_task(parent_id)
        if autonomy is None:
            autonomy = parent.get("autonomy") if parent else None
        if project_path is None:
            project_path = parent.get("project_path") if parent else None
    autonomy = autonomy or "guarded"
    if autonomy not in VALID_AUTONOMY:
        raise ValueError(f"invalid autonomy: {autonomy!r}")
    tid = _new_id()
    now = _now_str()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO tasks (id, parent_id, kind, title, detail, source, domain, "
            "priority, status, instruction, scheduled_for, autonomy, schedule_id, "
            "project_path, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (tid, parent_id, kind, title, detail, source, domain, priority,
             status, instruction, scheduled_for, autonomy, schedule_id,
             project_path, now, now),
        )
    return tid


def get_task(task_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    return dict(row) if row else None


def list_tasks(
    status: str | None = None,
    domain: str | None = None,
    assignee_session: str | None = None,
    parent_id: str | None = None,
) -> list[dict]:
    clauses, params = [], []
    for col, val in (("status", status), ("domain", domain),
                     ("assignee_session", assignee_session), ("parent_id", parent_id)):
        if val is not None:
            clauses.append(f"{col}=?")
            params.append(val)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM tasks {where} ORDER BY priority DESC, created_at ASC", params
        ).fetchall()
    return [dict(r) for r in rows]


# NOTE: "autonomy" is intentionally NOT updatable — it is set once at task
# creation (and inherited by worker_units from their parent). Do not add it
# here without also adding validation, the way "status" is validated.
_UPDATABLE = {
    "status", "domain", "priority", "assignee_session", "instruction",
    "result_summary", "artifact_path", "parent_id", "scheduled_for",
    "project_path",
}


def update_task(task_id: str, **fields) -> None:
    """Update whitelisted columns and bump updated_at."""
    if "status" in fields and fields["status"] not in VALID_STATUSES:
        raise ValueError(f"invalid status: {fields['status']!r}")
    sets = {k: v for k, v in fields.items() if k in _UPDATABLE}
    if not sets:
        return
    sets["updated_at"] = _now_str()
    assignments = ", ".join(f"{k}=?" for k in sets)
    with _connect() as conn:
        conn.execute(f"UPDATE tasks SET {assignments} WHERE id=?",
                     (*sets.values(), task_id))


def add_task_usage(
    task_id: str,
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    cost_usd: float = 0.0,
    turn_count: int = 0,
) -> None:
    """Atomically increment LLM usage counters on a task row."""
    if not any((input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, cost_usd, turn_count)):
        return
    now = _now_str()
    with _connect() as conn:
        cur = conn.execute(
            """
            UPDATE tasks SET
              usage_input_tokens = usage_input_tokens + ?,
              usage_output_tokens = usage_output_tokens + ?,
              usage_cache_read_tokens = usage_cache_read_tokens + ?,
              usage_cache_write_tokens = usage_cache_write_tokens + ?,
              usage_cost_usd = usage_cost_usd + ?,
              usage_turn_count = usage_turn_count + ?,
              updated_at = ?
            WHERE id = ?
            """,
            (
                max(0, input_tokens),
                max(0, output_tokens),
                max(0, cache_read_tokens),
                max(0, cache_write_tokens),
                max(0.0, cost_usd),
                max(0, turn_count),
                now,
                task_id,
            ),
        )
        if cur.rowcount == 0:
            logger.debug("add_task_usage: unknown task_id=%s", task_id)


def aggregate_task_usage(hours: int = 24) -> dict:
    """Sum usage across tasks touched in the last N hours (for board summary)."""
    cutoff = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT
              COALESCE(SUM(usage_input_tokens + usage_output_tokens), 0),
              COALESCE(SUM(usage_cost_usd), 0),
              COUNT(*) FILTER (WHERE usage_turn_count > 0)
            FROM tasks
            WHERE updated_at >= ?
            """,
            (cutoff,),
        ).fetchone()
    return {
        "total_tokens": int(row[0]),
        "total_cost_usd": round(float(row[1]), 4),
        "tasks_with_usage": int(row[2]),
        "hours": hours,
    }


def add_log(task_id: str, message: str, actor: str | None = None) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO task_logs (task_id, ts, actor, message) VALUES (?,?,?,?)",
            (task_id, _now_str(), actor, message),
        )


def list_logs(task_id: str, limit: int = 200) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM task_logs WHERE task_id=? ORDER BY id ASC LIMIT ?",
            (task_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def request_approval(task_id: str, action: str, payload: dict | None = None) -> int:
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO approvals (task_id, action, payload_json, status, created_at) "
            "VALUES (?,?,?,?,?)",
            (task_id, action, json.dumps(payload or {}, ensure_ascii=False),
             "pending", _now_str()),
        )
        return int(cur.lastrowid)


def get_approval(approval_id: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone()
    return dict(row) if row else None


def list_pending_approvals() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM approvals WHERE status='pending' ORDER BY id ASC"
        ).fetchall()
    return [dict(r) for r in rows]


def decide_approval(approval_id: int, approved: bool,
                    answer_text: str | None = None) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE approvals SET status=?, decided_at=?, answer_text=? WHERE id=?",
            ("approved" if approved else "rejected", _now_str(), answer_text,
             approval_id),
        )


def add_schedule(*, title: str, template: dict, cron_expr: str | None = None,
                 next_run_at: str | None = None, enabled: bool = True,
                 playbook: dict | None = None) -> int:
    now = _now_str()
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO schedules (title, template_json, playbook_json, cron_expr, "
            "next_run_at, enabled, updated_at) VALUES (?,?,?,?,?,?,?)",
            (title, json.dumps(template, ensure_ascii=False),
             json.dumps(playbook, ensure_ascii=False) if playbook else None,
             cron_expr, next_run_at, 1 if enabled else 0, now),
        )
        return int(cur.lastrowid)


def due_schedules(now: str) -> list[dict]:
    """Enabled schedules whose next_run_at has passed (string compare on ISO ts)."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM schedules WHERE enabled=1 AND next_run_at IS NOT NULL "
            "AND next_run_at <= ? ORDER BY next_run_at ASC",
            (now,),
        ).fetchall()
    return [dict(r) for r in rows]


def set_schedule_next_run(schedule_id: int, next_run_at: str) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE schedules SET next_run_at=?, updated_at=? WHERE id=?",
            (next_run_at, _now_str(), schedule_id),
        )


def _schedule_row(row: sqlite3.Row) -> dict:
    data = dict(row)
    try:
        data["template"] = json.loads(data.pop("template_json") or "{}")
    except json.JSONDecodeError:
        data["template"] = {}
    data["playbook"] = data.pop("playbook_json", None)
    return data


def list_schedules(*, enabled_only: bool = False) -> list[dict]:
    clause = "WHERE enabled=1" if enabled_only else ""
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM schedules {clause} ORDER BY id ASC"
        ).fetchall()
    return [_schedule_row(r) for r in rows]


def get_schedule(schedule_id: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM schedules WHERE id=?", (schedule_id,)).fetchone()
    return _schedule_row(row) if row else None


def update_schedule(schedule_id: int, **fields) -> None:
    mapping = {
        "title": "title",
        "template": "template_json",
        "playbook": "playbook_json",
        "cron_expr": "cron_expr",
        "next_run_at": "next_run_at",
        "enabled": "enabled",
        "last_run_at": "last_run_at",
        "last_task_id": "last_task_id",
    }
    sets: dict[str, object] = {}
    for key, col in mapping.items():
        if key not in fields:
            continue
        val = fields[key]
        if key == "template":
            val = json.dumps(val or {}, ensure_ascii=False)
        elif key == "playbook":
            val = json.dumps(val, ensure_ascii=False) if val is not None else None
        elif key == "enabled":
            val = 1 if val else 0
        sets[col] = val
    if not sets:
        return
    sets["updated_at"] = _now_str()
    assignments = ", ".join(f"{k}=?" for k in sets)
    with _connect() as conn:
        conn.execute(f"UPDATE schedules SET {assignments} WHERE id=?",
                     (*sets.values(), schedule_id))


def delete_schedule(schedule_id: int) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM schedules WHERE id=?", (schedule_id,))


def touch_schedule_run(schedule_id: int, task_id: str, *, success: bool = False) -> None:
    now = _now_str()
    fields: dict = {"last_run_at": now, "last_task_id": task_id}
    if success:
        sched = get_schedule(schedule_id)
        if sched:
            from devscope_bridge.schedule_playbook import merge_playbook, parse_playbook
            pb = parse_playbook(sched.get("playbook"))
            pb = merge_playbook(pb, {"last_success_at": now})
            fields["playbook"] = pb
    update_schedule(schedule_id, **fields)


def count_tasks_completed_since(hours: int = 24) -> int:
    cutoff = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    with _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE status='done' AND updated_at >= ?",
            (cutoff,),
        ).fetchone()
    return int(row[0]) if row else 0
