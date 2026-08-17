"""Tests for calendar event parsing and free-slot logic."""

from __future__ import annotations

from datetime import datetime, timedelta

from devscope_bridge.calendar import calendar_service, slots


def test_parse_event_with_meet_link():
    raw = {
        "id": "evt1",
        "summary": "Sync",
        "start": {"dateTime": "2026-06-15T10:00:00+03:00"},
        "end": {"dateTime": "2026-06-15T11:00:00+03:00"},
        "conferenceData": {
            "entryPoints": [{"entryPointType": "video", "uri": "https://meet.google.com/abc-defg-hij"}],
        },
        "attendees": [{"email": "dan@example.com"}],
    }
    parsed = calendar_service.parse_event(raw)
    assert parsed["summary"] == "Sync"
    assert parsed["meet_link"] == "https://meet.google.com/abc-defg-hij"
    assert parsed["attendees"] == ["dan@example.com"]
    assert parsed["all_day"] is False


def test_parse_event_all_day():
    raw = {
        "id": "evt2",
        "summary": "Holiday",
        "start": {"date": "2026-06-20"},
        "end": {"date": "2026-06-21"},
    }
    parsed = calendar_service.parse_event(raw)
    assert parsed["all_day"] is True


def test_find_free_slots_skips_busy():
    busy = [(datetime(2026, 6, 15, 10, 0), datetime(2026, 6, 15, 11, 0))]
    window_start = datetime(2026, 6, 15, 9, 0)
    window_end = datetime(2026, 6, 15, 18, 0)
    free = slots.find_free_slots(busy, window_start, window_end, 30, 3)
    assert free
    for slot in free:
        end = slot + timedelta(minutes=30)
        assert not slots._overlaps(slot, end, busy)
