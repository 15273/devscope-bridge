"""
task_usage.py — Map agent session names to orchestrator tasks and persist usage.

Worker sessions are named ``worker-{task_id}`` (see orchestrator._dispatch_worker).
Usage from each LLM turn is accumulated on the matching tasks row.
"""

from __future__ import annotations

import logging
import re

from devscope_bridge import task_store

logger = logging.getLogger(__name__)

_WORKER_SESSION = re.compile(r"^worker-([0-9a-f]{12})$")


def task_id_from_session(session_name: str) -> str | None:
    """Return task id when session_name is a worker assignee (worker-{id})."""
    m = _WORKER_SESSION.match(session_name)
    return m.group(1) if m else None


def record_turn_usage(session_name: str, event: dict) -> None:
    """Persist one result-event usage slice onto the worker task, if applicable."""
    task_id = task_id_from_session(session_name)
    if not task_id:
        return
    usage = event.get("usage") or {}
    try:
        task_store.add_task_usage(
            task_id,
            input_tokens=int(usage.get("input_tokens") or 0),
            output_tokens=int(usage.get("output_tokens") or 0),
            cache_read_tokens=int(usage.get("cache_read_input_tokens") or 0),
            cache_write_tokens=int(usage.get("cache_creation_input_tokens") or 0),
            cost_usd=float(event.get("total_cost_usd") or 0),
            turn_count=1,
        )
    except Exception:
        logger.debug("task usage write failed for %s", task_id, exc_info=True)


def usage_total_tokens(task: dict) -> int:
    """Input + output tokens recorded on a task row."""
    return int(task.get("usage_input_tokens") or 0) + int(task.get("usage_output_tokens") or 0)


def enrich_tasks_with_rollups(tasks: list[dict]) -> list[dict]:
    """Attach usage_total_tokens / usage_total_cost_usd including child worker units."""
    children_by_parent: dict[str, list[dict]] = {}
    for row in tasks:
        pid = row.get("parent_id")
        if pid:
            children_by_parent.setdefault(pid, []).append(row)

    enriched: list[dict] = []
    for row in tasks:
        out = dict(row)
        own_tokens = usage_total_tokens(out)
        own_cost = float(out.get("usage_cost_usd") or 0)
        child_rows = children_by_parent.get(out["id"], [])
        child_tokens = sum(usage_total_tokens(c) for c in child_rows)
        child_cost = sum(float(c.get("usage_cost_usd") or 0) for c in child_rows)
        out["usage_total_tokens"] = own_tokens + child_tokens
        out["usage_total_cost_usd"] = round(own_cost + child_cost, 4)
        enriched.append(out)
    return enriched
