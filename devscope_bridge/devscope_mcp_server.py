"""
devscope_mcp_server.py — MCP server (stdio) exposing DevScope capabilities to
Claude sessions as ONE tool: devscope_invoke.  Forwards to the bridge's
POST /invoke over loopback; the bridge routes to the right backend (cursor-agent
plugins like Notion, codebase scout, parallel ask) via the capability registry.

Claude CLI spawns this as a child process:
  .venv/bin/python -m devscope_bridge.devscope_mcp_server
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
# Must exceed the bridge-side backend timeout (cursor tasks run up to ~330s).
_INVOKE_TIMEOUT_S = 360.0


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


def _session() -> str | None:
    return os.environ.get("DEVSCOPE_SESSION") or None


async def _call(method: str, path: str, json_body: dict | None = None,
                timeout_s: float = 15.0) -> dict[str, Any]:
    token = _read_token()
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.request(
                method, f"{_BRIDGE_URL}{path}", json=json_body,
                headers={"Authorization": f"Bearer {token}"},
            )
    except httpx.RequestError as exc:
        return {"ok": False, "error": f"Bridge unreachable: {exc}"}
    if resp.status_code >= 400:
        return {"ok": False, "error": f"HTTP {resp.status_code}", "body": resp.text}
    return resp.json()


mcp = FastMCP(
    "devscope-control",
    instructions=(
        "Unified entry point to DevScope capabilities the direct MCP servers do NOT "
        "cover. Call devscope_invoke for Notion / Cursor-plugin questions and "
        "codebase scouting. Do NOT use it for browser, WhatsApp, Gmail, or Calendar — "
        "those have their own MCP tools. Call devscope_capabilities first when unsure "
        "what is available."
    ),
)


@mcp.tool()
async def devscope_invoke(capability: str, task: str, wait: bool = True) -> dict[str, Any]:
    """Run a DevScope capability (e.g. 'notion', 'codebase_scout') and return its result.

    wait=True blocks until the result (may take minutes for plugin tasks);
    wait=False starts it in the background and streams to the DevScope panel.
    """
    return await _call(
        "POST", "/invoke",
        json_body={"capability": capability, "task": task,
                   "session": _session(), "wait": wait},
        timeout_s=_INVOKE_TIMEOUT_S if wait else 15.0,
    )


@mcp.tool()
async def devscope_capabilities() -> dict[str, Any]:
    """List DevScope capabilities with live availability and setup hints."""
    result = await _call("GET", "/capabilities")
    if "capabilities" in result:
        return {"ok": True, "capabilities": result["capabilities"]}
    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    mcp.run(transport="stdio")
