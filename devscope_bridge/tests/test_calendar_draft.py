"""Tests for calendar event draft validation and body building."""

from __future__ import annotations

from devscope_bridge.calendar.event_draft import (
    build_google_event_body,
    normalize_attendees,
    validate_draft,
)


def test_validate_draft_requires_summary():
    err = validate_draft({"summary": "", "start": "2026-06-15T10:00:00", "end": "2026-06-15T11:00:00"})
    assert err is not None


def test_validate_draft_end_after_start():
    err = validate_draft({
        "summary": "Meet",
        "start": "2026-06-15T11:00:00",
        "end": "2026-06-15T10:00:00",
    })
    assert "סיום" in (err or "")


def test_build_google_event_body_with_meet():
    body = build_google_event_body({
        "summary": "Sync",
        "start": "2026-06-15T10:00:00+03:00",
        "end": "2026-06-15T11:00:00+03:00",
        "attendees": ["a@x.com", "a@x.com"],
        "add_google_meet": True,
    })
    assert body["summary"] == "Sync"
    assert len(body["attendees"]) == 1
    assert "conferenceData" in body


def test_normalize_attendees_dedupes():
    assert normalize_attendees(["A@X.com", "a@x.com"]) == ["a@x.com"]
