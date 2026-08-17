"""Pure helpers for calendar event drafts (validation + Google API body)."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_DEFAULT_TZ = "Asia/Jerusalem"


def normalize_attendees(emails: list[str]) -> list[str]:
    out: list[str] = []
    for raw in emails:
        email = raw.strip().lower()
        if email and email not in out:
            out.append(email)
    return out


def validate_draft(draft: dict[str, Any]) -> str | None:
    summary = (draft.get("summary") or "").strip()
    if not summary:
        return "נדרשת כותרת לאירוע"
    start_raw = draft.get("start")
    end_raw = draft.get("end")
    if not start_raw or not end_raw:
        return "נדרשים זמן התחלה וסיום"
    try:
        start = datetime.fromisoformat(str(start_raw).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(end_raw).replace("Z", "+00:00"))
    except ValueError:
        return "פורמט תאריך לא תקין (ISO)"
    if end <= start:
        return "שעת הסיום חייבת להיות אחרי ההתחלה"
    for email in normalize_attendees(draft.get("attendees") or []):
        if not _EMAIL_RE.match(email):
            return f"כתובת מייל לא תקינה: {email}"
    return None


def build_google_event_body(
    draft: dict[str, Any],
    *,
    timezone: str = _DEFAULT_TZ,
) -> dict[str, Any]:
    attendees = [
        {"email": e} for e in normalize_attendees(draft.get("attendees") or [])
    ]
    body: dict[str, Any] = {
        "summary": draft["summary"].strip(),
        "description": (draft.get("description") or "").strip(),
        "start": {"dateTime": draft["start"], "timeZone": timezone},
        "end": {"dateTime": draft["end"], "timeZone": timezone},
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "email", "minutes": 1440},
                {"method": "popup", "minutes": 30},
            ],
        },
    }
    location = (draft.get("location") or "").strip()
    if location:
        body["location"] = location
    if attendees:
        body["attendees"] = attendees
    if draft.get("add_google_meet"):
        body["conferenceData"] = {
            "createRequest": {
                "requestId": str(uuid.uuid4()),
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            },
        }
    return body
