"""Local SQLite mirror of WhatsApp cockpit state (~/.dev-bridge/wa_cockpit.db).

One responsibility: durable persistence of chats/messages/nudges so the nudge
engine can detect forgotten replies across time and the drafter has context.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS chats (
  id TEXT PRIMARY KEY, name TEXT, is_group INTEGER DEFAULT 0,
  in_scope INTEGER DEFAULT 0, muted INTEGER DEFAULT 0,
  last_msg_ts INTEGER DEFAULT 0, last_msg_from_me INTEGER DEFAULT 0,
  last_msg_preview TEXT DEFAULT '', updated_at INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY, chat_id TEXT, author TEXT, text TEXT,
  ts INTEGER DEFAULT 0, from_me INTEGER DEFAULT 0, type TEXT DEFAULT 'chat'
);
CREATE INDEX IF NOT EXISTS idx_messages_chat_ts ON messages(chat_id, ts);
CREATE TABLE IF NOT EXISTS nudges (
  chat_id TEXT PRIMARY KEY, since_ts INTEGER, state TEXT DEFAULT 'open',
  notified INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0
);
"""


def open_store(path: str | Path) -> sqlite3.Connection:
    """Open (creating if needed) the cockpit DB and ensure the schema exists."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(path), check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.executescript(_SCHEMA)
    db.commit()
    return db


def upsert_chat(db: sqlite3.Connection, chat: dict, *, in_scope: bool) -> None:
    """Upsert a chat row from an engine chat dict, preserving the muted flag."""
    last = chat.get("lastMessage") or {}
    db.execute(
        """INSERT INTO chats (id,name,is_group,in_scope,muted,last_msg_ts,
             last_msg_from_me,last_msg_preview,updated_at)
           VALUES (?,?,?,?,COALESCE((SELECT muted FROM chats WHERE id=?),0),?,?,?,?)
           ON CONFLICT(id) DO UPDATE SET name=excluded.name,is_group=excluded.is_group,
             in_scope=excluded.in_scope,last_msg_ts=excluded.last_msg_ts,
             last_msg_from_me=excluded.last_msg_from_me,
             last_msg_preview=excluded.last_msg_preview,updated_at=excluded.updated_at""",
        (chat["id"], chat.get("name", ""), int(bool(chat.get("isGroup"))),
         int(in_scope), chat["id"], int(last.get("ts", 0)),
         int(bool(last.get("fromMe"))), (last.get("preview") or "")[:200],
         int(time.time())),
    )
    db.commit()


def upsert_messages(db: sqlite3.Connection, chat_id: str, msgs: list[dict]) -> None:
    """Insert messages idempotently (ignore duplicates by id)."""
    db.executemany(
        """INSERT OR IGNORE INTO messages (id,chat_id,author,text,ts,from_me,type)
           VALUES (?,?,?,?,?,?,?)""",
        [(m["id"], chat_id, m.get("author", ""), m.get("text", ""),
          int(m.get("ts", 0)), int(bool(m.get("fromMe"))),
          m.get("type", "chat")) for m in msgs],
    )
    db.commit()


def list_chats(db: sqlite3.Connection) -> list[sqlite3.Row]:
    return db.execute("SELECT * FROM chats ORDER BY last_msg_ts DESC").fetchall()


def recent_messages(db: sqlite3.Connection, chat_id: str, limit: int) -> list[sqlite3.Row]:
    return db.execute(
        "SELECT * FROM messages WHERE chat_id=? ORDER BY ts DESC LIMIT ?",
        (chat_id, limit)).fetchall()


def set_muted(db: sqlite3.Connection, chat_id: str, muted: bool) -> None:
    db.execute("UPDATE chats SET muted=? WHERE id=?", (int(muted), chat_id))
    db.commit()


def find_chats_by_name(db: sqlite3.Connection, query: str, limit: int = 5) -> list[sqlite3.Row]:
    """Resolve chats whose name contains the query substring (most recent first)."""
    return db.execute(
        "SELECT * FROM chats WHERE name LIKE ? ORDER BY last_msg_ts DESC LIMIT ?",
        (f"%{query}%", limit),
    ).fetchall()


def get_chat(db: sqlite3.Connection, chat_id: str) -> sqlite3.Row | None:
    return db.execute("SELECT * FROM chats WHERE id=?", (chat_id,)).fetchone()
