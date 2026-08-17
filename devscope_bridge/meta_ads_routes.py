"""meta_ads_routes.py — FastAPI /meta/* router over Meta Marketing API."""

from __future__ import annotations

from pydantic import BaseModel, Field

from fastapi import APIRouter

from devscope_bridge import task_store
from devscope_bridge.meta_ads import cockpit_store, meta_ads_poller, meta_ads_service

router = APIRouter(prefix="/meta", tags=["meta-ads"])


class StatusBody(BaseModel):
    status: str = Field(description="ACTIVE or PAUSED")
    dry_run: bool = True


class BudgetBody(BaseModel):
    daily_budget: float = Field(gt=0)
    dry_run: bool = True


class DefaultAccountBody(BaseModel):
    ad_account_id: str


class AlertsConfigBody(BaseModel):
    enabled: bool | None = None
    ad_account_id: str | None = None
    date_preset: str | None = None
    thresholds: dict | None = None


class DailyReportScheduleBody(BaseModel):
    ad_account_id: str
    title: str = "Meta Ads daily report"
    daily_at: str = "09:00"
    agent: str = "claude"


@router.get("/health")
async def health() -> dict:
    return {
        "ok": True,
        "data": {
            "token_configured": meta_ads_service.token_configured(),
            "default_ad_account_id": meta_ads_service.default_ad_account_id(),
        },
    }


@router.get("/accounts")
async def accounts() -> dict:
    return await meta_ads_service.list_ad_accounts()


@router.get("/campaigns")
async def campaigns(ad_account_id: str | None = None, limit: int = 50) -> dict:
    return await meta_ads_service.list_campaigns(ad_account_id, limit=limit)


@router.get("/campaign")
async def campaign(campaign_id: str) -> dict:
    return await meta_ads_service.get_campaign(campaign_id)


@router.get("/insights")
async def insights(
    ad_account_id: str | None = None,
    date_preset: str = "last_7d",
    level: str = "campaign",
) -> dict:
    return await meta_ads_service.get_insights(ad_account_id, date_preset, level)


@router.post("/accounts/default")
async def set_default_account(body: DefaultAccountBody) -> dict:
    return await meta_ads_service.set_default_ad_account(body.ad_account_id)


@router.post("/campaigns/{campaign_id}/status")
async def campaign_status(campaign_id: str, body: StatusBody) -> dict:
    return await meta_ads_service.update_campaign_status(
        campaign_id, body.status, dry_run=body.dry_run,
    )


@router.post("/campaigns/{campaign_id}/budget")
async def campaign_budget(campaign_id: str, body: BudgetBody) -> dict:
    return await meta_ads_service.update_campaign_budget(
        campaign_id, body.daily_budget, dry_run=body.dry_run,
    )


@router.get("/alerts")
async def alerts(limit: int = 50) -> dict:
    db = cockpit_store.open_db()
    try:
        rows = cockpit_store.list_open_alerts(db, limit=limit)
        return {"ok": True, "data": rows, "error": None}
    finally:
        db.close()


@router.post("/alerts/{alert_id}/handled")
async def alert_handled(alert_id: int) -> dict:
    db = cockpit_store.open_db()
    try:
        cockpit_store.mark_handled(db, alert_id)
        return {"ok": True, "data": {"id": alert_id}, "error": None}
    finally:
        db.close()


@router.get("/alerts/config")
async def get_alerts_config() -> dict:
    return {"ok": True, "data": meta_ads_poller.load_config(), "error": None}


@router.post("/alerts/config")
async def post_alerts_config(body: AlertsConfigBody) -> dict:
    cfg = meta_ads_poller.load_config()
    if body.enabled is not None:
        cfg["enabled"] = body.enabled
    if body.ad_account_id is not None:
        cfg["ad_account_id"] = body.ad_account_id
    if body.date_preset is not None:
        cfg["date_preset"] = body.date_preset
    if body.thresholds is not None:
        cfg["thresholds"] = {**cfg.get("thresholds", {}), **body.thresholds}
    meta_ads_poller.save_config(cfg)
    return {"ok": True, "data": cfg, "error": None}


@router.post("/schedules/daily-report")
async def create_daily_report_schedule(body: DailyReportScheduleBody) -> dict:
    """Create a recurring schedule that materialises a meta_ads report task."""
    template = {
        "title": body.title,
        "kind": "mom_task",
        "domain": "meta_ads",
        "agent": body.agent,
        "mode": "act",
        "instruction": (
            f"Pull Meta Ads insights for ad account {body.ad_account_id} "
            f"(date_preset: today). Summarize spend, top campaigns, CPA/CTR. "
            f"Use meta_get_insights or /meta/insights. Log anomalies."
        ),
        "recurrence": {"daily_at": body.daily_at},
    }
    sid = task_store.add_schedule(
        title=body.title,
        template=template,
        enabled=True,
    )
    sched = task_store.get_schedule(sid)
    return {"ok": True, "data": sched, "error": None}
