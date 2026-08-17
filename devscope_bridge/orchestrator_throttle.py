"""Adjust orchestrator worker concurrency based on Claude quota utilization."""

from __future__ import annotations

import logging

from devscope_bridge import oauth_usage_service
from devscope_bridge.orchestrator_config import OrchestratorSettings

logger = logging.getLogger(__name__)


async def effective_max_workers(settings: OrchestratorSettings) -> tuple[int, dict]:
    """Return (effective cap, debug info) after optional quota throttle."""
    base = settings.to_config().max_workers
    info: dict = {
        "base_max_workers": base,
        "effective_max_workers": base,
        "quota_throttle_enabled": settings.quota_throttle_enabled,
        "utilization": None,
        "reason": "full_speed",
    }
    if not settings.quota_throttle_enabled:
        info["reason"] = "throttle_disabled"
        return base, info

    usage = await oauth_usage_service.get_usage()
    if not usage.get("available"):
        info["reason"] = "quota_unavailable"
        return base, info

    bucket = (usage.get("limits") or {}).get("five_hour") or {}
    util = bucket.get("utilization")
    if util is None:
        info["reason"] = "no_five_hour_bucket"
        return base, info

    util_pct = float(util)
    info["utilization"] = util_pct
    high = settings.quota_high_utilization
    mid = settings.quota_mid_utilization

    if util_pct >= high:
        effective = 1
        info["reason"] = "high_utilization"
    elif util_pct >= mid:
        effective = max(1, base // 2)
        info["reason"] = "mid_utilization"
    else:
        effective = base
        info["reason"] = "full_speed"

    info["effective_max_workers"] = effective
    if effective < base:
        logger.info(
            "orchestrator throttle: util=%.0f%% base=%d effective=%d (%s)",
            util_pct, base, effective, info["reason"],
        )
    return effective, info
