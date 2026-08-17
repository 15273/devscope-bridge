"""
task_links.py — mapping between local tasks and external board items (Notion, …).

Sibling of task_store (which is at its size budget): shares task_store._connect
so the bridge process remains the single SQLite writer. The (provider,
external_id) primary key is what makes external-board syncs idempotent.
"""

from __future__ import annotations

from datetime import datetime

from devscope_bridge.task_store import _connect

_SCHEMA = """
CREATE TABLE IF NOT EXISTS task_links (
    task_id      TEXT NOT NULL,
    provider     TEXT NOT NULL,
    external_id  TEXT NOT NULL,
    external_url TEXT,
    last_synced_at TEXT,
    push_hash    TEXT,
    PRIMARY KEY (provider, external_id)
);
CREATE INDEX IF NOT EXISTS idx_task_links_task ON task_links(task_id);
"""


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def ensure_schema() -> None:
    with _connect() as conn:
        conn.executescript(_SCHEMA)


def get_by_external(provider: str, external_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM task_links WHERE provider=? AND external_id=?",
            (provider, external_id),
        ).fetchone()
    return dict(row) if row else None


def get_by_task(task_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM task_links WHERE task_id=?", (task_id,),
        ).fetchone()
    return dict(row) if row else None


def list_links(provider: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM task_links WHERE provider=? ORDER BY last_synced_at ASC",
            (provider,),
        ).fetchall()
    return [dict(r) for r in rows]


def upsert_link(task_id: str, provider: str, external_id: str,
                external_url: str | None = None,
                push_hash: str | None = None) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO task_links (task_id, provider, external_id, external_url, "
            "last_synced_at, push_hash) VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(provider, external_id) DO UPDATE SET "
            "task_id=excluded.task_id, external_url=excluded.external_url, "
            "last_synced_at=excluded.last_synced_at, push_hash=excluded.push_hash",
            (task_id, provider, external_id, external_url, _now_str(), push_hash),
        )


def touch_push(provider: str, external_id: str, push_hash: str) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE task_links SET push_hash=?, last_synced_at=? "
            "WHERE provider=? AND external_id=?",
            (push_hash, _now_str(), provider, external_id),
        )
