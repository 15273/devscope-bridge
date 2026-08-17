"""calendar_service.py — Google Calendar read/write for DevScope cockpit."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from devscope_bridge.calendar import slots
from devscope_bridge.calendar.event_draft import (
    build_google_event_body,
    validate_draft,
)

_TOKEN_FILE = Path.home() / ".dev-bridge" / "calendar_token.json"
_READ_SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
_WRITE_SCOPE = "https://www.googleapis.com/auth/calendar.events"
_SCOPES = _READ_SCOPES + [_WRITE_SCOPE]
_DEFAULT_TZ = "Asia/Jerusalem"


def token_configured() -> bool:
    return _TOKEN_FILE.is_file()


def token_can_write() -> bool:
    if not _TOKEN_FILE.is_file():
        return False
    try:
        data = json.loads(_TOKEN_FILE.read_text())
        scopes = data.get("scopes") or []
        return _WRITE_SCOPE in scopes or "https://www.googleapis.com/auth/calendar" in scopes
    except (json.JSONDecodeError, OSError):
        return False


def parse_event(raw: dict[str, Any]) -> dict[str, Any]:
    """Convert a Google Calendar event into a compact summary (pure, testable)."""
    start = raw.get("start", {})
    end = raw.get("end", {})
    attendees = [
        a.get("email", "")
        for a in (raw.get("attendees") or [])
        if a.get("email")
    ]
    return {
        "id": raw.get("id"),
        "summary": raw.get("summary") or "(ללא כותרת)",
        "description": (raw.get("description") or "")[:500],
        "location": raw.get("location") or "",
        "start": start.get("dateTime") or start.get("date"),
        "end": end.get("dateTime") or end.get("date"),
        "all_day": bool(start.get("date") and not start.get("dateTime")),
        "status": raw.get("status"),
        "html_link": raw.get("htmlLink"),
        "meet_link": _extract_meet_link(raw),
        "attendees": attendees,
        "organizer": (raw.get("organizer") or {}).get("email"),
    }


def _extract_meet_link(raw: dict[str, Any]) -> str | None:
    entry_points = (raw.get("conferenceData") or {}).get("entryPoints") or []
    for ep in entry_points:
        if ep.get("entryPointType") == "video" and ep.get("uri"):
            return ep["uri"]
    if raw.get("hangoutLink"):
        return raw["hangoutLink"]
    return None


def _client():
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build  # type: ignore[import-untyped]

    creds = Credentials.from_authorized_user_file(str(_TOKEN_FILE), _SCOPES)
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def _default_window(days: int = 7) -> tuple[datetime, datetime]:
    now = datetime.now().replace(microsecond=0)
    return now, now + timedelta(days=days)


def _missing_token_error() -> dict[str, Any]:
    return {
        "ok": False,
        "data": None,
        "error": "calendar_token_missing — run: python -m devscope_bridge.calendar.authorize_calendar",
    }


def _missing_write_scope_error() -> dict[str, Any]:
    return {
        "ok": False,
        "data": None,
        "error": (
            "calendar_write_scope_missing — re-run authorize_calendar "
            "(token needs calendar.events scope)"
        ),
    }


async def list_events(
    time_min: datetime | None = None,
    time_max: datetime | None = None,
    *,
    calendar_id: str = "primary",
    limit: int = 50,
) -> dict[str, Any]:
    """List events in a time range. Returns {ok, data, error}."""
    if not token_configured():
        return _missing_token_error()
    if time_min is None or time_max is None:
        time_min, time_max = _default_window(7)
    try:
        svc = _client()
        res = (
            svc.events()
            .list(
                calendarId=calendar_id,
                timeMin=time_min.isoformat(),
                timeMax=time_max.isoformat(),
                maxResults=limit,
                singleEvents=True,
                orderBy="startTime",
                timeZone=_DEFAULT_TZ,
            )
            .execute()
        )
        events = [parse_event(e) for e in res.get("items", [])]
        return {"ok": True, "data": events, "error": None}
    except Exception as exc:
        return {"ok": False, "data": None, "error": str(exc)}


async def get_event(
    event_id: str,
    *,
    calendar_id: str = "primary",
) -> dict[str, Any]:
    """Fetch one event by ID. Returns {ok, data, error}."""
    if not token_configured():
        return _missing_token_error()
    try:
        svc = _client()
        raw = svc.events().get(calendarId=calendar_id, eventId=event_id).execute()
        return {"ok": True, "data": parse_event(raw), "error": None}
    except Exception as exc:
        return {"ok": False, "data": None, "error": str(exc)}


async def validate_event_draft(draft: dict[str, Any]) -> dict[str, Any]:
    err = validate_draft(draft)
    if err:
        return {"ok": False, "data": None, "error": err}
    return {"ok": True, "data": draft, "error": None}


async def create_event(
    draft: dict[str, Any],
    *,
    calendar_id: str = "primary",
) -> dict[str, Any]:
    """Create a calendar event (and optional Meet link + invites)."""
    if not token_configured():
        return _missing_token_error()
    if not token_can_write():
        return _missing_write_scope_error()
    err = validate_draft(draft)
    if err:
        return {"ok": False, "data": None, "error": err}
    try:
        svc = _client()
        body = build_google_event_body(draft)
        attendees = body.get("attendees") or []
        insert_kwargs: dict[str, Any] = {
            "calendarId": calendar_id,
            "body": body,
            "sendUpdates": "all" if attendees else "none",
        }
        if draft.get("add_google_meet"):
            insert_kwargs["conferenceDataVersion"] = 1
        raw = svc.events().insert(**insert_kwargs).execute()
        return {"ok": True, "data": parse_event(raw), "error": None}
    except Exception as exc:
        return {"ok": False, "data": None, "error": str(exc)}


async def suggest_free_slots(
    *,
    duration_minutes: int = 30,
    days_ahead: int = 7,
    count: int = 5,
    time_of_day: str | None = None,
    calendar_id: str = "primary",
) -> dict[str, Any]:
    """Find free meeting slots during work hours. Returns {ok, data, error}."""
    window_start, window_end = _default_window(days_ahead)
    listed = await list_events(window_start, window_end, calendar_id=calendar_id, limit=250)
    if not listed.get("ok"):
        return listed

    raw_events = listed.get("data") or []
    busy = slots.expand_busy_ranges(raw_events)
    free = slots.find_free_slots(
        busy,
        window_start,
        window_end,
        duration_minutes,
        count,
        time_of_day=time_of_day,
    )
    payload = [
        {
            "start": t.isoformat(),
            "end": (t + timedelta(minutes=duration_minutes)).isoformat(),
            "duration_minutes": duration_minutes,
        }
        for t in free
    ]
    return {"ok": True, "data": payload, "error": None}
