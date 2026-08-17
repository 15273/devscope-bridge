"""
status_helpers.py — /status card helpers.

Fetches the Claude CLI version once and caches it module-level.
Session info is read from session_manager / session_store metadata.
"""

import asyncio
import logging
import os

from devscope_bridge import session_manager, session_store

logger = logging.getLogger(__name__)

# Module-level cache so we only spawn `claude --version` once per bridge lifetime.
_cached_cli_version: str | None = None
_version_lock = asyncio.Lock()


async def _fetch_cli_version() -> str:
    """Run `claude --version` once; returns the version string or a fallback."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "claude", "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=session_manager.subscription_env(),
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
        return stdout.decode("utf-8", errors="replace").strip() or "unknown"
    except Exception as exc:  # noqa: BLE001
        logger.debug("claude --version failed: %s", exc)
        return "unknown"


async def get_cli_version() -> str:
    """Return cached CLI version; fetches once if not yet cached."""
    global _cached_cli_version
    if _cached_cli_version is not None:
        return _cached_cli_version
    async with _version_lock:
        if _cached_cli_version is None:
            _cached_cli_version = await _fetch_cli_version()
    return _cached_cli_version


def build_status_body(
    session_name: str,
    cli_version: str,
) -> str:
    """Build the /status card body text."""
    meta = session_store.get_metadata(session_name) or {}
    active = session_manager._sessions.get(session_name)

    model = (
        (active.model if active else None)
        or meta.get("model")
        or "default"
    )
    mode = (
        (active.mode if active else None)
        or meta.get("mode")
        or "act"
    )
    cwd = session_manager._session_cwd(session_name)
    session_id = meta.get("session_id") or "(none yet)"
    agent = meta.get("agent") or "claude"

    lines = [
        f"Session:      {session_name}",
        f"Session ID:   {session_id}",
        f"Agent:        {agent}",
        f"Model:        {model}",
        f"Mode:         {mode}",
        f"CWD:          {cwd}",
        f"CLI version:  {cli_version}",
    ]
    return "\n".join(lines)
