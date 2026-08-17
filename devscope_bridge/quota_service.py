"""
quota_service.py — the active Claude 5-hour usage block, via `ccusage`.

`ccusage blocks --active --json` reads the local ~/.claude transcripts and
reports the current 5-hour billing block: start/end time and tokens/cost burned.
This is the only available source for "when does my session reset" — the
stream-json output the bridge parses does not carry it.

Runs entirely locally (no model tokens), cached for `_TTL_S` so the panel can
poll cheaply. Degrades to `available: False` when ccusage is missing or errors.
"""

import asyncio
import json
import logging
import time

logger = logging.getLogger(__name__)

_TTL_S = 120.0          # serve cached result for 2 min between ccusage runs
_RUN_TIMEOUT_S = 20.0

_cache: dict | None = None
_cache_at = 0.0
_lock = asyncio.Lock()


def _empty() -> dict:
    return {"available": False}


def _parse_active_block(stdout: str) -> dict:
    """Extract the active block fields the panel battery needs."""
    data = json.loads(stdout)
    blocks = data.get("blocks") or []
    active = next((b for b in blocks if b.get("isActive")), None)
    if not active:
        return _empty()
    counts = active.get("tokenCounts") or {}
    projection = active.get("projection") or {}
    return {
        "available": True,
        "start_time": active.get("startTime"),
        "reset_at": active.get("endTime"),
        "remaining_minutes": projection.get("remainingMinutes"),
        "total_tokens": active.get("totalTokens"),
        "cost_usd": active.get("costUSD"),
        "input_tokens": counts.get("inputTokens"),
        "output_tokens": counts.get("outputTokens"),
        "projected_total_tokens": projection.get("totalTokens"),
        "projected_total_cost": projection.get("totalCost"),
    }


async def _run_ccusage() -> dict:
    """Run ccusage once; never raises — returns {available: False} on any error."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "npx", "ccusage", "blocks", "--active", "--json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=_RUN_TIMEOUT_S)
    except (FileNotFoundError, asyncio.TimeoutError) as exc:
        logger.info("ccusage unavailable (%s); quota battery disabled", type(exc).__name__)
        return _empty()
    except Exception as exc:  # noqa: BLE001 — must never break the poll loop
        logger.warning("ccusage run failed: %s", exc)
        return _empty()

    if proc.returncode != 0:
        logger.info("ccusage exited %s; quota battery disabled", proc.returncode)
        return _empty()
    try:
        return _parse_active_block(stdout.decode("utf-8", "replace"))
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        logger.warning("ccusage output parse failed: %s", exc)
        return _empty()


async def get_quota(force: bool = False) -> dict:
    """Return the cached active-block quota, refreshing when stale."""
    global _cache, _cache_at
    now = time.monotonic()
    if not force and _cache is not None and (now - _cache_at) < _TTL_S:
        return _cache
    async with _lock:
        now = time.monotonic()
        if not force and _cache is not None and (now - _cache_at) < _TTL_S:
            return _cache
        _cache = await _run_ccusage()
        _cache_at = time.monotonic()
        return _cache
