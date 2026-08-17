"""
oauth_usage_service.py — official Claude subscription usage, via `/api/oauth/usage`.

This is the same source the `claude` TUI `/usage` screen uses. It returns the
real plan utilization percentages (not derivable from ccusage):
  - five_hour  : the current 5-hour session block (% used + reset time)
  - seven_day  : the weekly limit across all models
  - seven_day_sonnet / _opus : per-model weekly limits
  - extra_usage: pay-as-you-go credits ("usage credits")

Auth reuses the OAuth access token Claude Code stores in the macOS Keychain
(service "Claude Code-credentials"). Runs locally, cached for `_TTL_S`.
Degrades to `{available: False}` when the token or endpoint is unavailable.
"""

import asyncio
import json
import logging
import time

import httpx

logger = logging.getLogger(__name__)

_USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
_BETA_HEADER = "oauth-2025-04-20"
_KEYCHAIN_SERVICE = "Claude Code-credentials"

_TTL_S = 60.0
_RUN_TIMEOUT_S = 8.0

_cache: dict | None = None
_cache_at = 0.0
_lock = asyncio.Lock()

# The buckets we surface to the panel, in display order.
_BUCKETS = ("five_hour", "seven_day", "seven_day_sonnet", "seven_day_opus")


def _empty() -> dict:
    return {"available": False}


async def _read_oauth_token() -> str | None:
    """Read the OAuth access token from the macOS Keychain."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "security", "find-generic-password", "-s", _KEYCHAIN_SERVICE, "-w",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=_RUN_TIMEOUT_S)
    except (FileNotFoundError, asyncio.TimeoutError):
        return None
    if proc.returncode != 0 or not stdout:
        return None
    try:
        return json.loads(stdout.decode("utf-8"))["claudeAiOauth"]["accessToken"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def _bucket(raw: dict, key: str) -> dict | None:
    """Normalise one usage bucket to {utilization, resets_at}."""
    data = raw.get(key)
    if not isinstance(data, dict) or data.get("utilization") is None:
        return None
    return {"utilization": data.get("utilization"), "resets_at": data.get("resets_at")}


def _parse(raw: dict) -> dict:
    limits = {k: b for k in _BUCKETS if (b := _bucket(raw, k)) is not None}
    if not limits:
        return _empty()
    extra = raw.get("extra_usage") or {}
    return {
        "available": True,
        "limits": limits,
        "extra_usage": {
            "is_enabled": bool(extra.get("is_enabled")),
            "utilization": extra.get("utilization"),
            "monthly_limit": extra.get("monthly_limit"),
            "currency": extra.get("currency"),
        },
    }


async def _fetch() -> dict:
    """Fetch usage once; never raises — returns {available: False} on any error."""
    token = await _read_oauth_token()
    if not token:
        logger.info("OAuth token unavailable; usage limits disabled")
        return _empty()
    headers = {
        "Authorization": f"Bearer {token}",
        "anthropic-beta": _BETA_HEADER,
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=_RUN_TIMEOUT_S) as client:
            resp = await client.get(_USAGE_URL, headers=headers)
    except httpx.HTTPError as exc:
        logger.info("usage fetch failed: %s", exc)
        return _empty()
    if resp.status_code != 200:
        logger.info("usage endpoint returned %s; limits disabled", resp.status_code)
        return _empty()
    try:
        return _parse(resp.json())
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        logger.warning("usage parse failed: %s", exc)
        return _empty()


async def get_usage(force: bool = False) -> dict:
    """Return the cached OAuth usage limits, refreshing when stale."""
    global _cache, _cache_at
    now = time.monotonic()
    if not force and _cache is not None and (now - _cache_at) < _TTL_S:
        return _cache
    async with _lock:
        now = time.monotonic()
        if not force and _cache is not None and (now - _cache_at) < _TTL_S:
            return _cache
        _cache = await _fetch()
        _cache_at = time.monotonic()
        return _cache
