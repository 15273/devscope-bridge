"""
meta_ads_mcp_server.py — MCP server exposing Meta Ads ops to Claude sessions.
"""

import logging
import os
from pathlib import Path
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

_TOKEN_FILE = Path.home() / ".dev-bridge" / "token"
_BRIDGE_URL = os.environ.get("BRIDGE_URL", "http://127.0.0.1:7878")


def _assert_loopback_bridge_url(url: str) -> None:
    if not any(url.startswith(p) for p in ("http://127.0.0.1", "http://localhost", "http://[::1]")):
        raise RuntimeError(f"BRIDGE_URL must target loopback only (got {url!r})")


_assert_loopback_bridge_url(_BRIDGE_URL)


def _read_token() -> str:
    if not _TOKEN_FILE.exists():
        raise RuntimeError(f"Bridge token not found at {_TOKEN_FILE}.")
    return _TOKEN_FILE.read_text().strip()


async def _call(
    method: str,
    path: str,
    *,
    params: dict | None = None,
    json_body: dict | None = None,
) -> dict[str, Any]:
    token = _read_token()
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.request(
                method,
                f"{_BRIDGE_URL}{path}",
                params=params,
                json=json_body,
                headers={"Authorization": f"Bearer {token}"},
            )
    except httpx.RequestError as exc:
        return {"ok": False, "error": f"Bridge unreachable: {exc}"}
    if resp.status_code >= 400:
        return {"ok": False, "error": f"HTTP {resp.status_code}", "body": resp.text}
    return resp.json()


mcp = FastMCP(
    "meta-ads-control",
    instructions=(
        "Meta (Facebook) Ads Manager via DevScope bridge. Token: "
        "~/.dev-bridge/meta_ads_token.json — run "
        "`python -m devscope_bridge.meta_ads.authorize_meta_ads` once. "
        "Write tools default to dry_run=true — set dry_run=false ONLY after user confirms."
    ),
)


@mcp.tool()
async def meta_list_accounts() -> dict[str, Any]:
    """List ad accounts available to the authenticated Meta user."""
    return await _call("GET", "/meta/accounts")


@mcp.tool()
async def meta_list_campaigns(
    ad_account_id: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """List campaigns for an ad account (uses default account if omitted)."""
    params = {"limit": limit}
    if ad_account_id:
        params["ad_account_id"] = ad_account_id
    return await _call("GET", "/meta/campaigns", params=params)


@mcp.tool()
async def meta_get_insights(
    ad_account_id: str | None = None,
    date_preset: str = "last_7d",
) -> dict[str, Any]:
    """Campaign-level insights: spend, impressions, clicks, CTR, CPC, actions."""
    params = {"date_preset": date_preset}
    if ad_account_id:
        params["ad_account_id"] = ad_account_id
    return await _call("GET", "/meta/insights", params=params)


@mcp.tool()
async def meta_update_campaign_status(
    campaign_id: str,
    status: str,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Pause (PAUSED) or activate (ACTIVE) a campaign. dry_run defaults to true."""
    return await _call(
        "POST",
        f"/meta/campaigns/{campaign_id}/status",
        json_body={"status": status, "dry_run": dry_run},
    )


@mcp.tool()
async def meta_update_campaign_budget(
    campaign_id: str,
    daily_budget: float,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Set daily budget in account currency. dry_run defaults to true."""
    return await _call(
        "POST",
        f"/meta/campaigns/{campaign_id}/budget",
        json_body={"daily_budget": daily_budget, "dry_run": dry_run},
    )


@mcp.tool()
async def meta_list_alerts(limit: int = 25) -> dict[str, Any]:
    """Open Meta Ads threshold alerts (spend, CPA)."""
    return await _call("GET", "/meta/alerts", params={"limit": limit})


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    mcp.run(transport="stdio")
