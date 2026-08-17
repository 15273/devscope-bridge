"""SQLite store for Meta Ads alerts and poller state."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

_DB = Path.home() / ".dev-bridge" / "meta_ads_alerts.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS alerts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  title TEXT NOT NULL,
  detail TEXT,
  ad_account_id TEXT,
  campaign_id TEXT,
  metric TEXT,
  value REAL,
  threshold REAL,
  state TEXT NOT NULL DEFAULT 'open',
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_alerts_state ON alerts(state);
"""


def open_db() -> sqlite3.Connection:
    _DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def list_open_alerts(conn: sqlite3.Connection, limit: int = 50) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM alerts WHERE state='open' ORDER BY updated_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def upsert_alert(
    conn: sqlite3.Connection,
    *,
    kind: str,
    title: str,
    detail: str,
    ad_account_id: str | None,
    campaign_id: str | None,
    metric: str,
    value: float,
    threshold: float,
) -> None:
    now = int(time.time())
    key_campaign = campaign_id or ""
    existing = conn.execute(
        """SELECT id FROM alerts
           WHERE state='open' AND kind=? AND metric=? AND campaign_id=?""",
        (kind, metric, key_campaign),
    ).fetchone()
    if existing:
        conn.execute(
            """UPDATE alerts SET title=?, detail=?, value=?, threshold=?, updated_at=?
               WHERE id=?""",
            (title, detail, value, threshold, now, existing["id"]),
        )
    else:
        conn.execute(
            """INSERT INTO alerts
               (kind, title, detail, ad_account_id, campaign_id, metric, value, threshold,
                state, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)""",
            (
                kind, title, detail, ad_account_id, campaign_id, metric,
                value, threshold, now, now,
            ),
        )
    conn.commit()


def mark_handled(conn: sqlite3.Connection, alert_id: int) -> None:
    conn.execute(
        "UPDATE alerts SET state='handled', updated_at=? WHERE id=?",
        (int(time.time()), alert_id),
    )
    conn.commit()
