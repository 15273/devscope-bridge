"""whatsapp_engine.py — structured WhatsApp read ops via the browser relay.

Each op sends a `browser_wa_store` action to the bound WA tab (MAIN world) and
returns {ok, data, error}. Write ops (send, mark_read) are gated behind
ENABLE_WA_COCKPIT_WRITE env flag.
"""
import os
from typing import Any
from devscope_bridge import browser_relay

# Last session that successfully reached WhatsApp. The cockpit poller probes
# profiles and the successful one is remembered here so write ops (send /
# mark_read), which have no panel binding, route to a profile that can reach the
# WA tab instead of an arbitrary first_active_session().
_last_good_session: str | None = None


async def _wa_store_action(
    op: str,
    params: dict[str, Any],
    session: str | None = None,
    *,
    quiet: bool = False,
) -> dict[str, Any]:
    # `session` routes the relay to the WS whose DevScope panel bound the
    # web.whatsapp.com tab. Without it, prefer the last session known to reach
    # WhatsApp before falling back to post_action's first_active_session().
    global _last_good_session
    if session is None:
        session = _last_good_session or browser_relay.first_active_session()
    body = browser_relay.ActionRequest(
        tool="browser_wa_store",
        args={"op": op, "params": params},
        session=session,
        quiet=quiet,
    )
    result = await browser_relay.post_action(body, auth=None)
    if result.get("ok") and session is not None:
        _last_good_session = session
    return result


async def list_chats(
    filter: str | None = None,
    limit: int = 50,
    session: str | None = None,
    *,
    quiet: bool = False,
) -> dict[str, Any]:
    """List WhatsApp chats; optionally filter by 'unread'."""
    return await _wa_store_action(
        "list_chats", {"filter": filter, "limit": limit}, session, quiet=quiet,
    )


async def get_messages(
    chat_id: str,
    limit: int = 30,
    session: str | None = None,
    *,
    quiet: bool = False,
) -> dict[str, Any]:
    """Get recent messages from a specific chat by ID."""
    return await _wa_store_action(
        "get_messages", {"chatId": chat_id, "limit": limit}, session, quiet=quiet,
    )


async def search(query: str, session: str | None = None, *, quiet: bool = False) -> dict[str, Any]:
    """Search chats by name substring."""
    return await _wa_store_action("search", {"query": query}, session, quiet=quiet)


def _writes_enabled() -> bool:
    return os.getenv("ENABLE_WA_COCKPIT_WRITE", "").lower() in ("1", "true", "yes")


async def send_message(chat_id: str, text: str, session: str | None = None) -> dict[str, Any]:
    """Send a text message to a chat. Requires ENABLE_WA_COCKPIT_WRITE=true."""
    if not _writes_enabled():
        return {"ok": False, "error": "writes_disabled"}
    return await _wa_store_action("send", {"chatId": chat_id, "text": text}, session)


async def mark_read(chat_id: str, session: str | None = None) -> dict[str, Any]:
    """Mark a chat as read. Requires ENABLE_WA_COCKPIT_WRITE=true."""
    if not _writes_enabled():
        return {"ok": False, "error": "writes_disabled"}
    return await _wa_store_action("mark_read", {"chatId": chat_id}, session)
