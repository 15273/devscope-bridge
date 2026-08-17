"""
external_board.py — bi-directional sync between the local task board and an
external board (Notion first; provider interface keeps Linear/Jira pluggable).

PULL: new actionable items on the external board become local mom_tasks
(source='notion'), idempotent via the task_links (provider, external_id) PK.
PUSH: linked local tasks whose status/summary/progress changed since the last
push update the external item (status + one progress comment), capped per sync.

The Notion round trip is a natural-language call through
capability_router.invoke("notion", ...) (cursor-agent plugin) — so pulls use a
strict JSON-only prompt and a tolerant parser. On any parse failure we do
NOTHING (never guess, never delete).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging

from devscope_bridge import capability_router, task_links, task_store
from devscope_bridge import orchestrator_core as oc
from devscope_bridge.employee_config import EmployeeSettings

logger = logging.getLogger(__name__)

# External statuses that mean "the employee should pick this up".
ACTIONABLE_STATUSES = {"to do", "todo", "not started", "backlog", "new", "ready"}

_STATUS_TO_EXTERNAL = {
    "new": "In progress", "assigned": "In progress", "ready": "In progress",
    "in_progress": "In progress", "awaiting_approval": "Blocked",
    "approved": "In progress", "done": "Done", "failed": "Blocked",
    "cancelled": "Done",
}

_PULL_PROMPT = (
    "List every item in the Notion database '{database}'. Respond with ONLY a "
    "JSON array — no prose, no markdown fences, no explanation. Each element: "
    '{{"id": "<notion page id>", "title": "<item title>", '
    '"status": "<status property value>", "url": "<page url>", '
    '"detail": "<one-line description or empty string>"}}. '
    "If the database is empty or not found, respond with []."
)

_PUSH_PROMPT = (
    "Update the Notion page with id '{item_id}': set its Status property to "
    "'{status}' and add a comment saying: {comment}. "
    "Reply with exactly DONE on success, or a one-line error."
)


class NotionProvider:
    id = "notion"

    async def pull(self, database: str) -> list[dict]:
        result = await capability_router.invoke(
            "notion", _PULL_PROMPT.format(database=database))
        if not result.get("ok"):
            logger.warning("notion pull failed: %s", result.get("error"))
            return []
        return _extract_json_array(result.get("detail") or result.get("summary") or "")

    async def push(self, item_id: str, status: str, comment: str) -> bool:
        result = await capability_router.invoke(
            "notion", _PUSH_PROMPT.format(
                item_id=item_id, status=status,
                comment=json.dumps(comment, ensure_ascii=False)))
        ok = bool(result.get("ok")) and "DONE" in (result.get("detail") or "")
        if not ok:
            logger.warning("notion push for %s failed: %s", item_id,
                           result.get("error") or (result.get("detail") or "")[:200])
        return ok


PROVIDERS = {"notion": NotionProvider}


def _extract_json_array(text: str) -> list[dict]:
    """Tolerant parse of an LLM reply that should be a JSON array of items.

    Strips prose/fences by slicing first '[' → last ']'. Any failure → [] —
    a bad sync round is a no-op, never a guess.
    """
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end <= start:
        return []
    try:
        parsed = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        logger.warning("external board reply was not valid JSON")
        return []
    if not isinstance(parsed, list):
        return []
    items = []
    for entry in parsed:
        if isinstance(entry, dict) and entry.get("id") and entry.get("title"):
            items.append({
                "external_id": str(entry["id"]),
                "title": str(entry["title"]),
                "status": str(entry.get("status") or ""),
                "url": str(entry.get("url") or ""),
                "detail": str(entry.get("detail") or ""),
            })
    return items


def _pull_new_items(provider_id: str, items: list[dict]) -> int:
    created = 0
    for item in items:
        if item["status"].strip().lower() not in ACTIONABLE_STATUSES:
            continue
        if task_links.get_by_external(provider_id, item["external_id"]):
            continue
        detail = "\n".join(filter(None, [item["url"], item["detail"]]))
        tid = task_store.create_task(
            title=item["title"], kind="mom_task", source="notion",
            detail=detail or None,
        )
        task_links.upsert_link(tid, provider_id, item["external_id"],
                               external_url=item["url"] or None)
        task_store.add_log(tid, actor="employee",
                           message=f"pulled from {provider_id}: {item['external_id']}")
        created += 1
    return created


def _push_payload(task: dict) -> tuple[str, str, str]:
    """(external_status, comment, push_hash) for one linked local task."""
    progress = oc.project_progress(task["id"])
    status = _STATUS_TO_EXTERNAL.get(task["status"], "In progress")
    summary = (task.get("result_summary") or "").strip()
    parts = [f"DevScope: {task['status']}"]
    if progress["total"]:
        parts.append(f"{progress['done']}/{progress['total']} steps ({progress['pct']}%)")
    if summary:
        parts.append(summary[:300])
    comment = " — ".join(parts)
    digest = hashlib.sha1(
        f"{task['status']}|{summary}|{progress['pct']}".encode()).hexdigest()
    return status, comment, digest


async def _push_changed(provider, cfg: EmployeeSettings) -> int:
    pushed = 0
    for link in task_links.list_links(provider.id):
        if pushed >= cfg.board_push_max_per_sync:
            break
        task = task_store.get_task(link["task_id"])
        if task is None:
            continue
        status, comment, digest = _push_payload(task)
        if digest == link.get("push_hash"):
            continue
        if await provider.push(link["external_id"], status, comment):
            task_links.touch_push(provider.id, link["external_id"], digest)
            pushed += 1
    return pushed


_sync_running = False


async def run_sync(cfg: EmployeeSettings) -> dict:
    """One pull+push round. Guarded against concurrent runs (NL round trips are slow)."""
    global _sync_running
    if _sync_running:
        return {"ok": False, "skipped": "sync already running"}
    provider_cls = PROVIDERS.get(cfg.board_provider)
    if provider_cls is None or not cfg.board_database:
        return {"ok": False, "error": "no provider/database configured"}
    _sync_running = True
    try:
        provider = provider_cls()
        items = await provider.pull(cfg.board_database)
        created = _pull_new_items(provider.id, items)
        pushed = await _push_changed(provider, cfg)
        logger.info("external board sync: %d pulled, %d created, %d pushed",
                    len(items), created, pushed)
        return {"ok": True, "seen": len(items), "created": created, "pushed": pushed}
    except Exception as exc:  # noqa: BLE001 — a bad sync must never hurt the tick
        logger.exception("external board sync failed")
        return {"ok": False, "error": str(exc)}
    finally:
        _sync_running = False
