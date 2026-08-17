"""
employee_routes.py — REST config/status surface for the Autonomous Employee.

GET/PATCH /employee/config   — read/update employee_config.json
POST /employee/test-channel  — send a test note through one channel
GET  /employee/status        — sync + channel health snapshot
"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from devscope_bridge import employee_comms, employee_config, task_links

router = APIRouter(prefix="/employee", tags=["employee"])


class EmployeePatchBody(BaseModel):
    employee_enabled: bool | None = None
    board_provider: str | None = None
    board_database: str | None = None
    board_sync_enabled: bool | None = None
    board_sync_every_ticks: int | None = None
    board_push_max_per_sync: int | None = None
    channels: dict[str, bool] | None = None
    wa_chat_id: str | None = None
    digest_email: str | None = None
    digest_daily_at: str | None = None


class TestChannelBody(BaseModel):
    channel: str


@router.get("/config")
def get_config() -> dict:
    return asdict(employee_config.load())


@router.patch("/config")
def patch_config(body: EmployeePatchBody) -> dict:
    settings = employee_config.patch(body.model_dump(exclude_none=True))
    if settings.employee_enabled and (settings.channels.get("email")
                                      or settings.channels.get("whatsapp")
                                      or settings.channels.get("panel")):
        employee_comms.ensure_digest_schedule(settings)
    return asdict(settings)


@router.post("/test-channel")
async def test_channel(body: TestChannelBody) -> dict:
    cfg = employee_config.load()
    if body.channel not in cfg.channels:
        raise HTTPException(status_code=422, detail=f"unknown channel: {body.channel}")
    test_cfg = employee_config.EmployeeSettings(**asdict(cfg))
    test_cfg.employee_enabled = True
    test_cfg.channels = {k: k == body.channel for k in cfg.channels}
    event = employee_comms.CommsEvent(
        kind="daily_digest", title="Test message",
        body="DevScope employee test — this channel works.")
    await employee_comms.notify(event, test_cfg)
    return {"ok": True, "channel": body.channel}


@router.get("/status")
def get_status() -> dict:
    from devscope_bridge.gmail.gmail_send import token_available
    from devscope_bridge.whatsapp.whatsapp_engine import _writes_enabled

    cfg = employee_config.load()
    links = task_links.list_links(cfg.board_provider)
    return {
        "enabled": cfg.employee_enabled,
        "provider": cfg.board_provider,
        "linked_tasks": len(links),
        "last_synced_at": max((l["last_synced_at"] or "" for l in links), default=None),
        "channel_health": {
            "panel": True,
            "notion": bool(cfg.board_database),
            "whatsapp": _writes_enabled() and bool(cfg.wa_chat_id),
            "email": token_available(),
        },
    }
