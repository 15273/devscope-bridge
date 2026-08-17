"""
whatsapp_mcp_server.py — MCP server (stdio) exposing WhatsApp read ops to Claude
sessions. Forwards every tool call to the dev_bridge /wa/* routes over loopback
so the bridge stays the single relay owner.

Claude CLI spawns this as a child process:
  .venv/bin/python -m devscope_bridge.whatsapp_mcp_server
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


def _bridge_session() -> str | None:
    """Session name from the Claude subprocess env (set by session_manager).

    Mirrors browser_mcp_server: WhatsApp Store ops run via the browser relay, so
    the action must be routed to THIS session's WS (whose DevScope panel bound the
    web.whatsapp.com tab) — not an arbitrary first_active_session().
    """
    return os.environ.get("DEVSCOPE_SESSION") or None


async def _call(
    method: str,
    path: str,
    params: dict | None = None,
    json_body: dict | None = None,
) -> dict[str, Any]:
    """Call a bridge route. For GET pass params=; for POST pass json_body=.

    The session query-param is always injected so the bridge routes the action
    to the correct WhatsApp tab binding. Backwards-compatible for GET callers
    that only pass params.
    """
    token = _read_token()
    query: dict[str, Any] = dict(params or {})
    session = _bridge_session()
    if session and "session" not in query:
        query["session"] = session
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.request(
                method, f"{_BRIDGE_URL}{path}",
                params=query,
                json=json_body,
                headers={"Authorization": f"Bearer {token}"},
            )
    except httpx.RequestError as exc:
        return {"ok": False, "error": f"Bridge unreachable: {exc}"}
    if resp.status_code >= 400:
        return {"ok": False, "error": f"HTTP {resp.status_code}", "body": resp.text}
    return resp.json()


mcp = FastMCP(
    "whatsapp-control",
    instructions=(
        "Read-only access to the WhatsApp Web session bound in the DevScope panel. "
        "The WA Store is grabbed from the MAIN world of the web.whatsapp.com tab via "
        "chrome.scripting.executeScript. If the tab is not open or the Store is not "
        "initialized, ops return {ok:false, error:'store_unavailable'}. "
        "Available ops: list chats, get messages in a chat, search chats by name. "
        "Write ops (send, mark_read) are deferred to Phase 3. "
        "Always handle store_unavailable gracefully — ask the user to open WhatsApp Web."
    ),
)


@mcp.tool()
async def wa_list_chats(
    filter: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """List WhatsApp chats. Pass filter='unread' to show only unread chats."""
    params: dict[str, Any] = {"limit": limit}
    if filter is not None:
        params["filter"] = filter
    return await _call("GET", "/wa/chats", params=params)


@mcp.tool()
async def wa_get_messages(chat_id: str, limit: int = 30) -> dict[str, Any]:
    """Get recent messages from a WhatsApp chat by its serialized ID (e.g. '972501234567@c.us')."""
    return await _call("GET", "/wa/messages", params={"chat_id": chat_id, "limit": limit})


@mcp.tool()
async def wa_search(query: str) -> dict[str, Any]:
    """Search WhatsApp chats by contact or group name substring."""
    return await _call("GET", "/wa/search", params={"query": query})


@mcp.tool()
async def wa_nudges() -> dict[str, Any]:
    """List WhatsApp chats waiting on a reply from the user (open nudges)."""
    return await _call("GET", "/wa/cockpit/nudges")


@mcp.tool()
async def wa_send(chat_id: str, text: str) -> dict[str, Any]:
    """Send a WhatsApp message to a chat.

    Gated by ENABLE_WA_COCKPIT_WRITE on the bridge — returns writes_disabled
    when the flag is off. Only call this after explicit user confirmation.
    """
    return await _call("POST", "/wa/cockpit/send", json_body={"chat_id": chat_id, "text": text})


@mcp.tool()
async def wa_mark_read(chat_id: str) -> dict[str, Any]:
    """Mark a WhatsApp chat nudge as handled (user dealt with it)."""
    return await _call("POST", "/wa/cockpit/handled", json_body={"chat_id": chat_id})


@mcp.tool()
async def wa_ask(question: str, chat_name: str | None = None,
                 chat_id: str | None = None) -> dict[str, Any]:
    """Ask about a WhatsApp chat using its saved history (scoped, cheap).

    Provide a chat_name (resolved by substring) or chat_id. Good for
    'what's going on in X's chat and what should I reply?'.
    """
    body: dict[str, Any] = {"question": question}
    if chat_id:
        body["chat_id"] = chat_id
    if chat_name:
        body["chat_name"] = chat_name
    return await _call("POST", "/wa/cockpit/ask", json_body=body)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    mcp.run(transport="stdio")
