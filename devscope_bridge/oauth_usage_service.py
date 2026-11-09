"""
oauth_usage_service.py — official Claude subscription usage, via `/api/oauth/usage`.

This is the same source the `claude` TUI `/usage` screen uses. It returns the
real plan utilization percentages (not derivable from ccusage):
  - five_hour  : the current 5-hour session block (% used + reset time)
  - seven_day  : the weekly limit across all models
  - seven_day_sonnet / _opus : per-model weekly limits
  - extra_usage: pay-as-you-go credits ("usage credits")

Auth reuses the OAuth access token Claude Code already stores locally:
  - macOS Keychain service "Claude Code-credentials" (preferred when present)
  - otherwise `~/.claude/.credentials.json` (Linux/Windows; respects
    `CLAUDE_CONFIG_DIR` the same way the CLI does)

Runs locally, cached for `_TTL_S`. Degrades to `{available: False}` when the
token or endpoint is unavailable. The access token is never logged.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

_USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
_BETA_HEADER = "oauth-2025-04-20"
_KEYCHAIN_SERVICE = "Claude Code-credentials"
_CREDENTIALS_FILENAME = ".credentials.json"

_TTL_S = 60.0
_RUN_TIMEOUT_S = 8.0

_cache: dict | None = None
_cache_at = 0.0
_lock = asyncio.Lock()

# The buckets we surface to the panel, in display order.
_BUCKETS = ("five_hour", "seven_day", "seven_day_sonnet", "seven_day_opus")


def _empty() -> dict:
    return {"available": False}


def _credentials_path() -> Path:
    """Path to Claude Code's credentials file (honours CLAUDE_CONFIG_DIR)."""
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    base = Path(config_dir) if config_dir else Path.home() / ".claude"
    return base / _CREDENTIALS_FILENAME


def _token_from_credentials_payload(data: object) -> str | None:
    """Extract accessToken from a Claude credentials JSON object. Never logs it."""
    if not isinstance(data, dict):
        return None
    oauth = data.get("claudeAiOauth")
    if not isinstance(oauth, dict):
        return None
    token = oauth.get("accessToken")
    if isinstance(token, str) and token.strip():
        return token
    return None


def _read_oauth_token_from_file() -> str | None:
    """Read the OAuth access token from Claude Code's credentials file."""
    path = _credentials_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        return _token_from_credentials_payload(json.loads(raw))
    except (json.JSONDecodeError, TypeError):
        return None


async def _read_oauth_token_from_keychain() -> str | None:
    """Read the OAuth access token from the macOS Keychain (no-op elsewhere)."""
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
        return _token_from_credentials_payload(json.loads(stdout.decode("utf-8")))
    except (json.JSONDecodeError, TypeError):
        return None


async def _read_oauth_token() -> str | None:
    """Keychain first (macOS); fall back to the credentials file on any platform."""
    token = await _read_oauth_token_from_keychain()
    if token:
        return token
    return await asyncio.to_thread(_read_oauth_token_from_file)


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
