"""Broadcast orchestrator board frames to every connected DevScope WS client."""

from __future__ import annotations

import asyncio
import logging

from devscope_bridge import browser_relay
from devscope_bridge.models import ApprovalRequest, TaskDigest, TaskUpdate

logger = logging.getLogger(__name__)


async def broadcast_text(text: str) -> None:
    await browser_relay.broadcast_text(text)


async def emit_task_digest(summary: str, counts: dict[str, int], report: str | None = None) -> None:
    frame = TaskDigest(summary=summary, counts=counts, report=report)
    await broadcast_text(frame.model_dump_json())


async def emit_task_update(
    task_id: str,
    title: str,
    status: str,
    domain: str | None = None,
    note: str | None = None,
) -> None:
    frame = TaskUpdate(
        task_id=task_id, title=title, status=status, domain=domain, note=note,
    )
    await broadcast_text(frame.model_dump_json())


def notify_task_update(
    task_id: str,
    title: str,
    status: str,
    domain: str | None = None,
    note: str | None = None,
) -> None:
    """Fire-and-forget from sync route handlers."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(emit_task_update(task_id, title, status, domain, note))


async def emit_approval_request(
    task_id: str,
    title: str,
    action: str,
    payload: dict | None = None,
    approval_id: int | None = None,
) -> None:
    frame = ApprovalRequest(
        task_id=task_id,
        title=title,
        action=action,
        payload=payload or {},
        approval_id=approval_id,
    )
    await broadcast_text(frame.model_dump_json())


def notify_approval_request(
    task_id: str,
    title: str,
    action: str,
    payload: dict | None = None,
    approval_id: int | None = None,
) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(
        emit_approval_request(task_id, title, action, payload, approval_id),
    )
