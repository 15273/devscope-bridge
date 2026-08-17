"""
usage_audit.py — Diagnose Claude token burn: active block, session ranking, task backlog.

Read-only local inspection (ccusage + agent_tasks.db + sessions.json). Safe to run anytime.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import subprocess
from collections import Counter
from pathlib import Path

logger = logging.getLogger(__name__)

BRIDGE_DIR = Path.home() / ".dev-bridge"
SESSIONS_FILE = BRIDGE_DIR / "sessions.json"
TASKS_DB = BRIDGE_DIR / "agent_tasks.db"
_CCUSAGE_TIMEOUT_S = 45.0


def _run_ccusage(*args: str) -> dict | list | None:
    try:
        proc = subprocess.run(
            ["npx", "ccusage", *args],
            capture_output=True,
            text=True,
            timeout=_CCUSAGE_TIMEOUT_S,
            check=False,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return None
        return json.loads(proc.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError) as exc:
        logger.info("ccusage %s failed: %s", args[:2], exc)
        return None


def _session_tokens(row: dict) -> int:
    if row.get("totalTokens"):
        return int(row["totalTokens"])
    tc = row.get("tokenCounts") or {}
    return sum(
        int(tc.get(k) or 0)
        for k in ("inputTokens", "outputTokens", "cacheReadInputTokens", "cacheCreationInputTokens")
    )


def _load_bridge_session_map() -> dict[str, str]:
    """claude session_id → DevScope session name."""
    if not SESSIONS_FILE.is_file():
        return {}
    try:
        data = json.loads(SESSIONS_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    sessions = data.get("sessions", data)
    out: dict[str, str] = {}
    for name, meta in sessions.items():
        if isinstance(meta, dict) and meta.get("session_id"):
            out[str(meta["session_id"])] = name
    return out


def _task_backlog() -> dict:
    if not TASKS_DB.is_file():
        return {"available": False}
    conn = sqlite3.connect(TASKS_DB)
    conn.row_factory = sqlite3.Row
    try:
        total = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        by_status = dict(conn.execute(
            "SELECT status, COUNT(*) c FROM tasks GROUP BY status ORDER BY c DESC"
        ).fetchall())
        by_source = dict(conn.execute(
            "SELECT COALESCE(source,'?'), COUNT(*) FROM tasks GROUP BY source ORDER BY COUNT(*) DESC"
        ).fetchall())
        queued = sum(by_status.get(s, 0) for s in ("new", "assigned", "ready", "approved"))
        in_progress = by_status.get("in_progress", 0)
        top_usage = [
            dict(r) for r in conn.execute(
                """
                SELECT id, title, status, kind, source,
                       usage_input_tokens + usage_output_tokens AS tokens,
                       usage_cost_usd, usage_turn_count, assignee_session, updated_at
                FROM tasks WHERE usage_turn_count > 0
                ORDER BY tokens DESC LIMIT 10
                """
            ).fetchall()
        ]
        return {
            "available": True,
            "total_tasks": total,
            "queued": queued,
            "in_progress": in_progress,
            "by_status": by_status,
            "by_source": by_source,
            "top_task_usage": top_usage,
        }
    finally:
        conn.close()


def _load_orchestrator_config() -> dict:
    cfg_path = BRIDGE_DIR / "orchestrator_config.json"
    if not cfg_path.is_file():
        return {"auto_hygiene_enabled": True}
    try:
        return json.loads(cfg_path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _rank_sessions(limit: int = 30) -> list[dict]:
    raw = _run_ccusage("claude", "session", "-j", "-O", "--order", "desc")
    if raw is None:
        return []
    items = raw if isinstance(raw, list) else raw.get("sessions") or raw.get("entries") or []
    id_to_name = _load_bridge_session_map()
    ranked: list[dict] = []
    for row in items:
        if not isinstance(row, dict):
            continue
        cid = str(row.get("sessionId") or row.get("id") or "")
        tokens = _session_tokens(row)
        if tokens <= 0:
            continue
        bridge_name = id_to_name.get(cid)
        ranked.append({
            "claude_session_id": cid,
            "bridge_session": bridge_name,
            "total_tokens": tokens,
            "cost_usd": float(row.get("costUSD") or row.get("cost") or 0),
            "is_orchestrator": bridge_name in ("mom", "mgr-research", "mgr-dev", "mgr-browser")
                or (bridge_name or "").startswith("worker-")
                or (bridge_name or "").startswith("mgr-"),
        })
    ranked.sort(key=lambda x: x["total_tokens"], reverse=True)
    return ranked[:limit]


def _active_block() -> dict:
    raw = _run_ccusage("blocks", "--active", "--json")
    if not raw or not isinstance(raw, dict):
        return {"available": False}
    blocks = raw.get("blocks") or []
    active = next((b for b in blocks if b.get("isActive")), None)
    if not active:
        return {"available": False}
    tc = active.get("tokenCounts") or {}
    br = active.get("burnRate") or {}
    return {
        "available": True,
        "total_tokens": active.get("totalTokens"),
        "cost_usd": active.get("costUSD"),
        "entries": active.get("entries"),
        "models": active.get("models"),
        "start_time": active.get("startTime"),
        "reset_at": active.get("endTime"),
        "input_tokens": tc.get("inputTokens"),
        "output_tokens": tc.get("outputTokens"),
        "cache_read_tokens": tc.get("cacheReadInputTokens"),
        "cache_creation_tokens": tc.get("cacheCreationInputTokens"),
        "burn_tokens_per_minute": br.get("tokensPerMinute"),
        "burn_cost_per_hour": br.get("costPerHour"),
        "cache_pct_of_total": round(
            100 * (int(tc.get("cacheReadInputTokens") or 0) + int(tc.get("cacheCreationInputTokens") or 0))
            / max(1, int(active.get("totalTokens") or 1)),
            1,
        ),
    }


def _bridge_session_stats() -> dict:
    if not SESSIONS_FILE.is_file():
        return {}
    try:
        data = json.loads(SESSIONS_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    sessions = data.get("sessions", data)
    prefixes = Counter()
    for name in sessions:
        if name.startswith("worker-"):
            prefixes["worker"] += 1
        elif name.startswith("mgr-"):
            prefixes["mgr"] += 1
        elif name == "mom":
            prefixes["mom"] += 1
        else:
            prefixes["user"] += 1
    return {"total_sessions": len(sessions), "by_kind": dict(prefixes)}


def _agent_session_stats() -> dict:
    """Count Claude vs Cursor sessions and automation sessions with resume ids."""
    if not SESSIONS_FILE.is_file():
        return {"available": False}
    try:
        from devscope_bridge import session_hygiene
        data = json.loads(SESSIONS_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {"available": False}
    sessions = data.get("sessions", data)
    by_agent: Counter[str] = Counter()
    automation_with_resume = 0
    cursor_with_resume = 0
    for name, meta in sessions.items():
        if not isinstance(meta, dict):
            continue
        agent = meta.get("agent", "claude")
        by_agent[agent] += 1
        if meta.get("session_id"):
            if agent == "cursor":
                cursor_with_resume += 1
            if session_hygiene.is_automation_session(name, meta):
                automation_with_resume += 1
    return {
        "available": True,
        "by_agent": dict(by_agent),
        "cursor_with_resume_id": cursor_with_resume,
        "automation_with_resume_id": automation_with_resume,
    }


def _side_channel_risks() -> list[dict]:
    """Dev-bridge features that spawn extra LLM calls (not ccusage-tracked for Cursor)."""
    return [
        {"id": "english_coach", "trigger": "each user message when coach_enabled", "agent": "claude --print", "risk": "medium"},
        {"id": "background_ask", "trigger": "/ask command", "agent": "claude --print", "risk": "low"},
        {"id": "cursor_ctx", "trigger": "/cursor-ctx", "agent": "cursor-agent scout + claude turn", "risk": "high"},
        {"id": "watchdog_medic", "trigger": "stuck turn >3min silence", "agent": "claude --print", "risk": "low"},
        {"id": "compact", "trigger": "/compact", "agent": "claude --print summarizer", "risk": "low"},
        {"id": "wa_cockpit_draft", "trigger": "user clicks draft reply", "agent": "claude --print", "risk": "low"},
        {"id": "orchestrator", "trigger": "tick loop", "agent": "claude/cursor sessions", "risk": "high if hygiene off"},
        {"id": "cursor_user_chat", "trigger": "each message with --resume", "agent": "cursor-agent", "risk": "grows with thread length"},
    ]


def _recommendations(
    block: dict,
    backlog: dict,
    orch: dict,
    top_sessions: list[dict],
) -> list[str]:
    recs: list[str] = []
    if orch.get("auto_hygiene_enabled") is not False:
        recs.insert(0, "Auto session hygiene is ON — mom/mgr reset each tick, recovery backlog capped, workers pruned.")
    if orch.get("paused") is not True:
        queued = backlog.get("queued", 0)
        if queued > 50:
            recs.append(
                f"Orchestrator is RUNNING with {queued} queued tasks — pause it immediately "
                "(Task Board → Pause) to stop autonomous worker turns."
            )
    mgr_huge = [
        s for s in top_sessions[:5]
        if s.get("bridge_session") in ("mom", "mgr-research", "mgr-dev")
        and s.get("total_tokens", 0) > 50_000_000
    ]
    if mgr_huge and orch.get("auto_hygiene_enabled") is False:
        names = ", ".join(s["bridge_session"] for s in mgr_huge)
        recs.append(
            f"Orchestrator manager sessions ({names}) have 50M+ lifetime tokens — enable auto hygiene or /new."
        )
    elif mgr_huge:
        recs.append(
            "Large lifetime totals on mom/mgr-* are historical — auto hygiene resets before each new tick."
        )
    if block.get("available") and (block.get("cache_pct_of_total") or 0) > 70:
        recs.append(
            f"Current 5h block is {block['cache_pct_of_total']}% cache tokens — "
            "long sessions re-read huge context each turn. Reset mom/mgr-* and old worker sessions."
        )
    if backlog.get("by_source", {}).get("ats_recovery", 0) > 100:
        recs.append(
            f"{backlog['by_source']['ats_recovery']} ATS-recovery tasks in DB — "
            "bulk-cancel ready/assigned recovery tasks or pause the enqueuer."
        )
    workers = _bridge_session_stats().get("by_kind", {}).get("worker", 0)
    if workers > 100:
        recs.append(
            f"{workers} worker-* sessions registered — each may resume with stale context. "
            "Prune old workers in sessions.json or /new after tasks complete."
        )
    if not recs:
        recs.append("No critical backlog detected — check top sessions for unexpected high totals.")
    return recs


def run_audit() -> dict:
    """Synchronous full audit — safe to call from CLI or FastAPI route."""
    block = _active_block()
    backlog = _task_backlog()
    orch = _load_orchestrator_config()
    top_sessions = _rank_sessions(25)
    return {
        "active_block": block,
        "task_backlog": backlog,
        "orchestrator": orch,
        "bridge_sessions": _bridge_session_stats(),
        "agent_sessions": _agent_session_stats(),
        "side_channels": _side_channel_risks(),
        "top_sessions": top_sessions,
        "recommendations": _recommendations(block, backlog, orch, top_sessions),
    }


async def get_audit() -> dict:
    """Async wrapper — runs ccusage in a thread so the event loop stays responsive."""
    return await asyncio.to_thread(run_audit)


if __name__ == "__main__":
    import pprint
    pprint.pp(run_audit(), width=100)
