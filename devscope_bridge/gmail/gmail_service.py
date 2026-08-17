"""gmail_service.py — read-only Gmail API access for the email cockpit.

Builds a client from a stored OAuth token; exposes search/get/labels.
parse_thread/_header are pure and unit-tested without network.
Heavy google-api imports live inside _client() so module import stays light.
"""
from pathlib import Path
from typing import Any

_TOKEN_FILE = Path.home() / ".dev-bridge" / "gmail_token.json"
_SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


def token_configured() -> bool:
    return _TOKEN_FILE.is_file()


def _header(headers: list[dict], name: str) -> str:
    """Return the value of the first header matching name (case-insensitive)."""
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def parse_thread(raw: dict[str, Any]) -> dict[str, Any]:
    """Convert a raw Gmail thread dict into a structured summary.

    Pure function — no network, no imports. Safe to unit-test directly.
    """
    msgs = []
    subject = ""
    for m in raw.get("messages", []):
        headers = m.get("payload", {}).get("headers", [])
        subject = subject or _header(headers, "Subject")
        msgs.append({
            "from": _header(headers, "From"),
            "date": _header(headers, "Date"),
            "snippet": m.get("snippet", ""),
        })
    return {"id": raw.get("id"), "subject": subject, "messages": msgs}


def _client():
    """Build an authenticated Gmail API service from the stored token file."""
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build  # type: ignore[import-untyped]
    creds = Credentials.from_authorized_user_file(str(_TOKEN_FILE), _SCOPES)
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


async def search_threads(q: str, limit: int = 25) -> dict[str, Any]:
    """Search Gmail threads by query string. Returns {ok, data, error}."""
    try:
        svc = _client()
        res = svc.users().threads().list(userId="me", q=q, maxResults=limit).execute()
        return {"ok": True, "data": res.get("threads", []), "error": None}
    except Exception as exc:
        return {"ok": False, "data": None, "error": str(exc)}


async def get_thread(thread_id: str) -> dict[str, Any]:
    """Fetch a single thread by ID and parse it. Returns {ok, data, error}."""
    try:
        svc = _client()
        raw = svc.users().threads().get(
            userId="me", id=thread_id, format="metadata",
        ).execute()
        return {"ok": True, "data": parse_thread(raw), "error": None}
    except Exception as exc:
        return {"ok": False, "data": None, "error": str(exc)}


async def list_labels() -> dict[str, Any]:
    """List all Gmail labels for the authenticated user. Returns {ok, data, error}."""
    try:
        svc = _client()
        res = svc.users().labels().list(userId="me").execute()
        return {"ok": True, "data": res.get("labels", []), "error": None}
    except Exception as exc:
        return {"ok": False, "data": None, "error": str(exc)}
