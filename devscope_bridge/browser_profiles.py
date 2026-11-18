"""Named browser profiles (daily + QA) and their CDP endpoints.

DevScope's standing Chrome (the daily profile) usually listens on
127.0.0.1:9222. HireMe QA starts a second official Chrome under a different
user-data-dir and debug port. Both should be addressable as named profiles
so an agent can say ``profile=qa`` or ``profile=daily``.

Endpoints come from, in order:
1. The ``DEVSCOPE_CDP_ENDPOINTS`` env var
   (``daily=127.0.0.1:9222,qa=127.0.0.1:9336`` or a bare ``host:port`` = daily)
2. Optional ``~/.dev-bridge/cdp-endpoints.json``
   (``{"daily": "127.0.0.1:9222", "qa": "127.0.0.1:9336"}``)
3. The built-in default daily endpoint ``127.0.0.1:9222``
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from devscope_bridge.bridge_auth import BRIDGE_DIR

logger = logging.getLogger(__name__)

DEFAULT_DAILY_CDP = "127.0.0.1:9222"
ENDPOINTS_FILE = BRIDGE_DIR / "cdp-endpoints.json"

# Tools that are safe to run over the token-auth CDP fallback when the
# extension side panel is not connected.
CDP_FALLBACK_TOOLS = frozenset({
    "browser_list_tabs",
    "browser_get_page_info",
    "browser_navigate",
    "browser_evaluate",
    "browser_screenshot",
    "browser_get_console",
    "browser_get_network",
    "browser_click",
    "browser_fill",
    "browser_assert_text",
    "browser_wait_for_selector",
})


@dataclass(frozen=True)
class BrowserProfile:
    name: str
    cdp: str  # host:port, loopback only
    label: str = ""

    def display_label(self) -> str:
        return self.label or self.name


def _assert_loopback_cdp(hostport: str) -> str:
    raw = hostport.strip()
    if raw.startswith("http://"):
        raw = raw[len("http://"):]
    if raw.startswith("ws://"):
        raw = raw[len("ws://"):]
    raw = raw.rstrip("/")
    host, sep, port = raw.partition(":")
    if not sep or not port.isdigit():
        raise ValueError(f"CDP endpoint must be host:port, got {hostport!r}")
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError(f"CDP endpoint must be loopback-only, refusing host={host!r}")
    # Canonicalize localhost → 127.0.0.1 so health/compare is stable
    if host == "localhost":
        host = "127.0.0.1"
    return f"{host}:{int(port)}"


def parse_endpoints_spec(spec: str) -> dict[str, str]:
    """Parse ``name=host:port,name=host:port`` or a bare ``host:port`` (daily)."""
    out: dict[str, str] = {}
    for part in (spec or "").split(","):
        part = part.strip()
        if not part:
            continue
        if "=" in part:
            name, _, hostport = part.partition("=")
            name = name.strip()
            hostport = hostport.strip()
        else:
            name, hostport = "daily", part
        if not name:
            raise ValueError(f"empty profile name in {spec!r}")
        out[name] = _assert_loopback_cdp(hostport)
    return out


def _from_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not read CDP endpoints file %s: %s", path, exc)
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, str] = {}
    for name, hostport in data.items():
        if not isinstance(name, str) or not isinstance(hostport, str):
            continue
        try:
            out[name] = _assert_loopback_cdp(hostport)
        except ValueError as exc:
            logger.warning("Ignoring CDP endpoint %s: %s", name, exc)
    return out


def load_profiles(
    env: dict[str, str] | None = None,
    endpoints_file: Path | None = None,
    *,
    include_default_daily: bool = True,
) -> list[BrowserProfile]:
    """Named profiles, env first, then the endpoints file, then the daily default."""
    environ = env if env is not None else os.environ
    merged: dict[str, str] = {}
    file_path = endpoints_file if endpoints_file is not None else ENDPOINTS_FILE
    merged.update(_from_file(file_path))
    spec = environ.get("DEVSCOPE_CDP_ENDPOINTS", "")
    if spec.strip():
        merged.update(parse_endpoints_spec(spec))
    if include_default_daily and "daily" not in merged:
        merged["daily"] = DEFAULT_DAILY_CDP
    profiles = [
        BrowserProfile(name=name, cdp=cdp, label=name)
        for name, cdp in merged.items()
    ]
    # daily first, then qa, then the rest alphabetically
    rank = {"daily": 0, "qa": 1}
    profiles.sort(key=lambda p: (rank.get(p.name, 50), p.name))
    return profiles


def get_profile(name: str | None, profiles: Iterable[BrowserProfile] | None = None) -> BrowserProfile | None:
    if not name:
        return None
    wanted = name.strip().lower()
    for profile in (profiles if profiles is not None else load_profiles()):
        if profile.name.lower() == wanted:
            return profile
    return None
