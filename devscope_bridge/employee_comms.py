"""
employee_comms.py — proactive communication channels for the Autonomous Employee.

One CommsEvent fans out to the enabled channels (panel / notion / whatsapp /
email). Every channel is best-effort: a failing channel logs and never blocks
the others or the caller. The daily digest is deterministic Python (no LLM),
scheduled through the schedules table as a `builtin` template.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from devscope_bridge import board_relay, task_links, task_store
from devscope_bridge import orchestrator_core as oc
from devscope_bridge.employee_config import EmployeeSettings, load as load_config
from devscope_bridge.models import EmployeeNote

logger = logging.getLogger(__name__)

_PANEL_FOOTER = "\n\nAnswer in the DevScope panel."


@dataclass
class CommsEvent:
    kind: str            # question | blocker | milestone_done | project_done | daily_digest
    title: str
    body: str = ""
    task_id: str | None = None


async def _send_panel(event: CommsEvent) -> None:
    frame = EmployeeNote(kind=event.kind, title=event.title,
                         body=event.body, task_id=event.task_id)
    await board_relay.broadcast_text(frame.model_dump_json())


async def _send_notion(event: CommsEvent) -> None:
    if not event.task_id:
        return
    link = task_links.get_by_task(event.task_id)
    if link is None:
        return
    from devscope_bridge import external_board

    provider = external_board.PROVIDERS.get(link["provider"])
    if provider is None:
        return
    task = task_store.get_task(event.task_id) or {}
    status, _, _ = external_board._push_payload(task) if task else ("Blocked", "", "")
    await provider().push(link["external_id"], status, f"{event.title}: {event.body}"[:500])


async def _send_whatsapp(event: CommsEvent, cfg: EmployeeSettings) -> None:
    if not cfg.wa_chat_id:
        return
    from devscope_bridge.whatsapp import whatsapp_engine

    text = f"🤖 DevScope — {event.title}\n{event.body}"
    if event.kind in ("question", "blocker"):
        text += _PANEL_FOOTER
    result = await whatsapp_engine.send_message(cfg.wa_chat_id, text)
    if not result.get("ok"):
        logger.info("whatsapp channel unavailable: %s", result.get("error"))


async def _send_email(event: CommsEvent, cfg: EmployeeSettings) -> None:
    from devscope_bridge.gmail import gmail_send

    body = event.body + (_PANEL_FOOTER if event.kind in ("question", "blocker") else "")
    result = await gmail_send.send_message(
        cfg.digest_email, f"DevScope employee — {event.title}", body)
    if not result.get("ok"):
        logger.info("email channel unavailable: %s", result.get("error"))


async def notify(event: CommsEvent, cfg: EmployeeSettings | None = None) -> None:
    """Fan an event out to every enabled channel, best-effort per channel."""
    cfg = cfg or load_config()
    if not cfg.employee_enabled:
        return
    senders = {
        "panel": lambda: _send_panel(event),
        "notion": lambda: _send_notion(event),
        "whatsapp": lambda: _send_whatsapp(event, cfg),
        "email": lambda: _send_email(event, cfg),
    }
    for channel, make_coro in senders.items():
        if not cfg.channels.get(channel):
            continue
        try:
            await make_coro()
        except Exception:  # noqa: BLE001 — one channel must never break the rest
            logger.exception("employee comms channel '%s' failed", channel)


def notify_question(task: dict, action: str, payload: dict | None) -> None:
    """Fire-and-forget hook for task_routes.request_approval."""
    import asyncio

    payload = payload or {}
    if action == "question":
        event = CommsEvent(kind="question", title=task["title"],
                           body=str(payload.get("question") or ""),
                           task_id=task["id"])
    else:
        event = CommsEvent(kind="blocker", title=task["title"],
                           body=f"Waiting for approval: {action}",
                           task_id=task["id"])
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(notify(event))


# ── daily digest (deterministic — no LLM tokens) ────────────────────────────

def _digest_body() -> str:
    completed = task_store.count_tasks_completed_since(hours=24)
    usage = task_store.aggregate_task_usage(hours=24)
    failed = [t for t in task_store.list_tasks(status="failed")]
    pending = task_store.list_pending_approvals()
    questions = [a for a in pending if a.get("action") == "question"]
    blockers = [a for a in pending if a.get("action") != "question"]

    lines = [f"Completed in the last 24h: {completed} tasks."]
    cost = usage.get("total_cost_usd") or 0
    if cost:
        lines.append(f"Estimated spend: ${cost:.2f}.")
    roots = [t for t in task_store.list_tasks(status="in_progress")
             if not t.get("parent_id") and t.get("kind") != "worker_unit"]
    for root in roots[:10]:
        p = oc.project_progress(root["id"])
        if p["total"]:
            lines.append(f"• {root['title']}: {p['done']}/{p['total']} steps ({p['pct']}%)")
    if questions:
        lines.append(f"Open questions waiting for you: {len(questions)}.")
    if blockers:
        lines.append(f"Approvals waiting for you: {len(blockers)}.")
    if failed:
        lines.append(f"Failed (last on board): {len(failed)} — see the Tasks panel.")
    return "\n".join(lines)


async def run_daily_digest() -> None:
    await notify(CommsEvent(kind="daily_digest", title="Daily summary",
                            body=_digest_body()))


# Builtin callables the scheduler can run instead of materialising a task.
BUILTINS = {"daily_digest": run_daily_digest}


def _is_digest_schedule(sched: dict) -> bool:
    import json

    tmpl = sched.get("template")
    if not isinstance(tmpl, dict):
        try:
            tmpl = json.loads(sched.get("template_json") or "{}")
        except json.JSONDecodeError:
            return False
    return tmpl.get("builtin") == "daily_digest"


def ensure_digest_schedule(cfg: EmployeeSettings) -> None:
    """Seed (once) the daily-digest schedule row so the Schedules tab manages it.

    next_run_at must be non-NULL — due_schedules skips NULL rows.
    """
    if any(_is_digest_schedule(s) for s in task_store.list_schedules()):
        return
    recurrence = {"daily_at": cfg.digest_daily_at}
    first_run = oc._next_run_at(recurrence, oc._now())
    task_store.add_schedule(
        title="Daily employee digest",
        template={"builtin": "daily_digest", "recurrence": recurrence},
        next_run_at=first_run,
        enabled=True,
    )
