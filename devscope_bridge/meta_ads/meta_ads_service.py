"""meta_ads_service.py — Meta Marketing API via stored OAuth token."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx

_TOKEN_FILE = Path.home() / ".dev-bridge" / "meta_ads_token.json"
_GRAPH_VERSION = os.environ.get("FACEBOOK_GRAPH_VERSION", "v21.0").strip()
_GRAPH_BASE = f"https://graph.facebook.com/{_GRAPH_VERSION}"


def token_configured() -> bool:
    return _TOKEN_FILE.is_file() and _TOKEN_FILE.stat().st_size > 2


def _load_token() -> dict[str, Any]:
    if not token_configured():
        raise FileNotFoundError(
            f"Missing {_TOKEN_FILE}. Run: python -m devscope_bridge.meta_ads.authorize_meta_ads"
        )
    return json.loads(_TOKEN_FILE.read_text())


def _access_token() -> str:
    data = _load_token()
    token = data.get("access_token")
    if not token:
        raise ValueError("meta_ads_token.json has no access_token")
    return str(token)


def default_ad_account_id() -> str | None:
    if not token_configured():
        return None
    raw = _load_token().get("default_ad_account_id")
    return str(raw) if raw else None


def _normalize_account_id(ad_account_id: str) -> str:
    aid = ad_account_id.strip()
    if aid.startswith("act_"):
        return aid
    return f"act_{aid}"


def parse_campaign(raw: dict[str, Any]) -> dict[str, Any]:
    """Pure — map Graph campaign node to cockpit shape."""
    daily = raw.get("daily_budget")
    lifetime = raw.get("lifetime_budget")
    return {
        "id": raw.get("id"),
        "name": raw.get("name") or "(unnamed)",
        "status": raw.get("status"),
        "effective_status": raw.get("effective_status"),
        "objective": raw.get("objective"),
        "daily_budget": int(daily) / 100 if daily else None,
        "lifetime_budget": int(lifetime) / 100 if lifetime else None,
    }


def parse_insight_row(raw: dict[str, Any]) -> dict[str, Any]:
    """Pure — normalize insights metrics."""
    spend = raw.get("spend")
    impressions = raw.get("impressions")
    clicks = raw.get("clicks")
    ctr = raw.get("ctr")
    cpc = raw.get("cpc")
    cpm = raw.get("cpm")
    return {
        "campaign_id": raw.get("campaign_id"),
        "campaign_name": raw.get("campaign_name"),
        "date_start": raw.get("date_start"),
        "date_stop": raw.get("date_stop"),
        "spend": float(spend) if spend is not None else 0.0,
        "impressions": int(impressions or 0),
        "clicks": int(clicks or 0),
        "ctr": float(ctr) if ctr is not None else 0.0,
        "cpc": float(cpc) if cpc is not None else 0.0,
        "cpm": float(cpm) if cpm is not None else 0.0,
        "actions": raw.get("actions") or [],
    }


async def _graph_get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    q = dict(params or {})
    q["access_token"] = _access_token()
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(f"{_GRAPH_BASE}/{path.lstrip('/')}", params=q)
    if resp.status_code >= 400:
        return {"ok": False, "data": None, "error": resp.text}
    return {"ok": True, "data": resp.json(), "error": None}


async def _graph_post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    body = {**payload, "access_token": _access_token()}
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(f"{_GRAPH_BASE}/{path.lstrip('/')}", data=body)
    if resp.status_code >= 400:
        return {"ok": False, "data": None, "error": resp.text}
    return {"ok": True, "data": resp.json(), "error": None}


async def list_ad_accounts() -> dict[str, Any]:
    try:
        res = await _graph_get(
            "me/adaccounts",
            {
                "fields": "id,name,account_id,currency,account_status",
                "limit": 50,
            },
        )
        if not res["ok"]:
            return res
        rows = res["data"].get("data", [])
        return {"ok": True, "data": rows, "error": None}
    except Exception as exc:
        return {"ok": False, "data": None, "error": str(exc)}


async def list_campaigns(
    ad_account_id: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    try:
        aid = _normalize_account_id(ad_account_id or default_ad_account_id() or "")
        if not aid or aid == "act_":
            return {"ok": False, "data": None, "error": "ad_account_id required"}
        res = await _graph_get(
            f"{aid}/campaigns",
            {
                "fields": "id,name,status,effective_status,objective,daily_budget,lifetime_budget",
                "limit": limit,
            },
        )
        if not res["ok"]:
            return res
        parsed = [parse_campaign(c) for c in res["data"].get("data", [])]
        return {"ok": True, "data": parsed, "error": None}
    except Exception as exc:
        return {"ok": False, "data": None, "error": str(exc)}


async def get_campaign(campaign_id: str) -> dict[str, Any]:
    try:
        res = await _graph_get(
            campaign_id,
            {
                "fields": "id,name,status,effective_status,objective,daily_budget,lifetime_budget",
            },
        )
        if not res["ok"]:
            return res
        return {"ok": True, "data": parse_campaign(res["data"]), "error": None}
    except Exception as exc:
        return {"ok": False, "data": None, "error": str(exc)}


async def get_insights(
    ad_account_id: str | None = None,
    date_preset: str = "last_7d",
    level: str = "campaign",
) -> dict[str, Any]:
    try:
        aid = _normalize_account_id(ad_account_id or default_ad_account_id() or "")
        if not aid or aid == "act_":
            return {"ok": False, "data": None, "error": "ad_account_id required"}
        res = await _graph_get(
            f"{aid}/insights",
            {
                "fields": "campaign_id,campaign_name,spend,impressions,clicks,ctr,cpc,cpm,actions",
                "date_preset": date_preset,
                "level": level,
                "limit": 100,
            },
        )
        if not res["ok"]:
            return res
        parsed = [parse_insight_row(r) for r in res["data"].get("data", [])]
        return {"ok": True, "data": parsed, "error": None}
    except Exception as exc:
        return {"ok": False, "data": None, "error": str(exc)}


async def update_campaign_status(
    campaign_id: str,
    status: str,
    *,
    dry_run: bool = True,
) -> dict[str, Any]:
    """status: ACTIVE | PAUSED"""
    status = status.upper()
    if status not in {"ACTIVE", "PAUSED"}:
        return {"ok": False, "data": None, "error": "status must be ACTIVE or PAUSED"}
    try:
        before = await get_campaign(campaign_id)
        if not before["ok"]:
            return before
        preview = {
            "campaign_id": campaign_id,
            "before": before["data"],
            "after": {**before["data"], "status": status},
            "dry_run": dry_run,
        }
        if dry_run:
            return {"ok": True, "data": preview, "error": None}
        res = await _graph_post(campaign_id, {"status": status})
        if not res["ok"]:
            return res
        return {"ok": True, "data": preview, "error": None}
    except Exception as exc:
        return {"ok": False, "data": None, "error": str(exc)}


async def update_campaign_budget(
    campaign_id: str,
    daily_budget: float,
    *,
    dry_run: bool = True,
) -> dict[str, Any]:
    """daily_budget in account currency (e.g. 50.0 = $50). Stored as cents in API."""
    if daily_budget <= 0:
        return {"ok": False, "data": None, "error": "daily_budget must be positive"}
    try:
        before = await get_campaign(campaign_id)
        if not before["ok"]:
            return before
        cents = int(round(daily_budget * 100))
        preview = {
            "campaign_id": campaign_id,
            "before": before["data"],
            "after": {**before["data"], "daily_budget": daily_budget},
            "daily_budget_cents": cents,
            "dry_run": dry_run,
        }
        if dry_run:
            return {"ok": True, "data": preview, "error": None}
        res = await _graph_post(campaign_id, {"daily_budget": str(cents)})
        if not res["ok"]:
            return res
        return {"ok": True, "data": preview, "error": None}
    except Exception as exc:
        return {"ok": False, "data": None, "error": str(exc)}


async def set_default_ad_account(ad_account_id: str) -> dict[str, Any]:
    try:
        data = _load_token()
        data["default_ad_account_id"] = _normalize_account_id(ad_account_id)
        _TOKEN_FILE.write_text(json.dumps(data, indent=2))
        return {"ok": True, "data": {"default_ad_account_id": data["default_ad_account_id"]}, "error": None}
    except Exception as exc:
        return {"ok": False, "data": None, "error": str(exc)}
