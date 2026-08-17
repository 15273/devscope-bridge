"""
gmail_send.py — minimal Gmail send for employee notifications (daily digest).

Uses the SAME stored token as gmail_service (scope gmail.modify permits
users.messages.send) — no re-auth needed. Kept separate so gmail_service and
the gmail MCP surface stay read-only.
"""

from __future__ import annotations

import base64
from email.mime.text import MIMEText
from typing import Any

from devscope_bridge.gmail.gmail_service import _client, _TOKEN_FILE


def token_available() -> bool:
    return _TOKEN_FILE.is_file()


async def send_message(to: str, subject: str, body: str) -> dict[str, Any]:
    """Send a plain-text email. Empty ``to`` sends to the authenticated account."""
    if not token_available():
        return {"ok": False, "error": f"gmail token missing at {_TOKEN_FILE}"}
    try:
        svc = _client()
        recipient = to.strip()
        if not recipient:
            profile = svc.users().getProfile(userId="me").execute()
            recipient = profile["emailAddress"]
        msg = MIMEText(body, "plain", "utf-8")
        msg["To"] = recipient
        msg["Subject"] = subject
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        sent = svc.users().messages().send(userId="me", body={"raw": raw}).execute()
        return {"ok": True, "id": sent.get("id"), "to": recipient}
    except Exception as exc:  # noqa: BLE001 — channel is best-effort
        return {"ok": False, "error": str(exc)}
