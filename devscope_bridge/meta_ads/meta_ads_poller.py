"""Background poller — Meta Ads threshold alerts."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from devscope_bridge.meta_ads import cockpit_store, meta_ads_service

logger = logging.getLogger(__name__)

_CONFIG = Path.home() / ".dev-bridge" / "meta_ads_alerts_config.json"
_POLL_S = 300

_DEFAULT_CONFIG = {
    "enabled": True,
    "ad_account_id": None,
    "date_preset": "today",
    "thresholds": {
        "daily_spend": 500.0,
        "cpa": 80.0,
    },
}


def load_config() -> dict:
    if not _CONFIG.is_file():
        return dict(_DEFAULT_CONFIG)
    try:
        data = json.loads(_CONFIG.read_text())
        merged = dict(_DEFAULT_CONFIG)
        merged.update(data)
        merged["thresholds"] = {**_DEFAULT_CONFIG["thresholds"], **(data.get("thresholds") or {})}
        return merged
    except Exception:
        return dict(_DEFAULT_CONFIG)


def save_config(cfg: dict) -> None:
    _CONFIG.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG.write_text(json.dumps(cfg, indent=2))


async def _tick() -> None:
    if not meta_ads_service.token_configured():
        return
    cfg = load_config()
    if not cfg.get("enabled", True):
        return
    aid = cfg.get("ad_account_id") or meta_ads_service.default_ad_account_id()
    if not aid:
        accounts = await meta_ads_service.list_ad_accounts()
        if accounts.get("ok") and accounts.get("data"):
            aid = accounts["data"][0].get("id")
    if not aid:
        return

    insights = await meta_ads_service.get_insights(
        aid, date_preset=cfg.get("date_preset", "today"), level="campaign",
    )
    if not insights.get("ok"):
        logger.debug("meta ads poll: insights failed: %s", insights.get("error"))
        return

    thresholds = cfg.get("thresholds") or {}
    spend_limit = float(thresholds.get("daily_spend", 0) or 0)
    cpa_limit = float(thresholds.get("cpa", 0) or 0)
    db = cockpit_store.open_db()
    try:
        total_spend = sum(r["spend"] for r in insights["data"])
        if spend_limit > 0 and total_spend >= spend_limit:
            cockpit_store.upsert_alert(
                db,
                kind="spend",
                title="Daily spend threshold exceeded",
                detail=f"Account spend {total_spend:.2f} >= {spend_limit:.2f}",
                ad_account_id=aid,
                campaign_id=None,
                metric="spend",
                value=total_spend,
                threshold=spend_limit,
            )
        for row in insights["data"]:
            spend = row["spend"]
            if spend <= 0 or cpa_limit <= 0:
                continue
            actions = row.get("actions") or []
            leads = 0
            for act in actions:
                if act.get("action_type") in {"lead", "offsite_conversion.fb_pixel_lead", "link_click"}:
                    leads += int(float(act.get("value", 0)))
            if leads <= 0:
                continue
            cpa = spend / leads
            if cpa >= cpa_limit:
                cockpit_store.upsert_alert(
                    db,
                    kind="cpa",
                    title=f"High CPA: {row.get('campaign_name', row.get('campaign_id'))}",
                    detail=f"CPA {cpa:.2f} >= {cpa_limit:.2f}",
                    ad_account_id=aid,
                    campaign_id=row.get("campaign_id"),
                    metric="cpa",
                    value=cpa,
                    threshold=cpa_limit,
                )
    finally:
        db.close()


async def run_forever() -> None:
    while True:
        try:
            await _tick()
        except Exception:
            logger.exception("meta ads poller tick failed")
        await asyncio.sleep(_POLL_S)
