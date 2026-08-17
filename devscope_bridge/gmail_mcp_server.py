"""
gmail_mcp_server.py — MCP server (stdio) exposing Gmail read ops to Claude
sessions. Forwards every tool call to the dev_bridge /gm/* routes over
loopback so the bridge stays the single relay owner.

Claude CLI spawns this as a child process:
  .venv/bin/python -m devscope_bridge.gmail_mcp_server
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
    """Reject any BRIDGE_URL that doesn't target loopback."""
    loopback_prefixes = (
        "http://127.0.0.1",
        "http://localhost",
        "http://[::1]",
    )
    if not any(url.startswith(p) for p in loopback_prefixes):
        raise RuntimeError(
            f"BRIDGE_URL must target loopback only (got {url!r}). "
            "Set BRIDGE_URL=http://127.0.0.1:7878 or leave unset."
        )


_assert_loopback_bridge_url(_BRIDGE_URL)


def _read_token() -> str:
    if not _TOKEN_FILE.exists():
        raise RuntimeError(f"Bridge token not found at {_TOKEN_FILE}.")
    return _TOKEN_FILE.read_text().strip()


async def _call(method: str, path: str, params: dict | None = None) -> dict[str, Any]:
    token = _read_token()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.request(
                method, f"{_BRIDGE_URL}{path}",
                params=params,
                headers={"Authorization": f"Bearer {token}"},
            )
    except httpx.RequestError as exc:
        return {"ok": False, "error": f"Bridge unreachable: {exc}"}
    if resp.status_code >= 400:
        return {"ok": False, "error": f"HTTP {resp.status_code}", "body": resp.text}
    return resp.json()


mcp = FastMCP(
    "gmail-control",
    instructions=(
        "Read-only access to the Gmail account authenticated via OAuth in the DevScope "
        "bridge. Token lives at ~/.dev-bridge/gmail_token.json — run "
        "`python -m devscope_bridge.gmail.authorize_gmail` once to set it up. "
        "Supports searching threads (Gmail query syntax), fetching a single thread, "
        "and listing labels. Write ops (send, archive, label) are deferred to Phase 3. "
        "If the token is missing or expired, ops return {ok:false, error:'...'} — "
        "ask the user to re-run the authorize script."
    ),
)


@mcp.tool()
async def gm_search_threads(
    q: str = "in:inbox",
    limit: int = 25,
) -> dict[str, Any]:
    """Search Gmail threads using Gmail query syntax (e.g. 'from:boss@co.com is:unread').

    Returns a list of thread stubs with id and snippet.
    """
    return await _call("GET", "/gm/threads", params={"q": q, "limit": limit})


@mcp.tool()
async def gm_get_thread(thread_id: str) -> dict[str, Any]:
    """Fetch a single Gmail thread by its ID and return parsed subject + messages."""
    return await _call("GET", "/gm/thread", params={"thread_id": thread_id})


@mcp.tool()
async def gm_list_labels() -> dict[str, Any]:
    """List all Gmail labels for the authenticated user."""
    return await _call("GET", "/gm/labels")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    mcp.run(transport="stdio")
