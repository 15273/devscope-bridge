"""Find free calendar slots from busy event ranges."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any, Optional

WORK_START_HOUR = 9
WORK_END_HOUR = 18
BUFFER_MINUTES = 15
SLOT_STEP_MINUTES = 30

TIME_OF_DAY_RANGES = {
    "morning": (9, 12),
    "afternoon": (12, 17),
    "evening": (17, 18),
}


def parse_event_bounds(event: dict[str, Any]) -> Optional[tuple[datetime, datetime]]:
    start_raw = event.get("start")
    end_raw = event.get("end")
    if isinstance(start_raw, str) and isinstance(end_raw, str):
        start_str, end_str = start_raw, end_raw
    else:
        start_dict = start_raw if isinstance(start_raw, dict) else event.get("start", {})
        end_dict = end_raw if isinstance(end_raw, dict) else event.get("end", {})
        start_str = start_dict.get("dateTime") or start_dict.get("date")
        end_str = end_dict.get("dateTime") or end_dict.get("date")
    if not start_str or not end_str:
        return None
    try:
        start = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
        end = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
        if start.tzinfo:
            start = start.replace(tzinfo=None)
        if end.tzinfo:
            end = end.replace(tzinfo=None)
        return start, end
    except ValueError:
        return None


def expand_busy_ranges(
    events: list[dict[str, Any]],
    buffer_minutes: int = BUFFER_MINUTES,
) -> list[tuple[datetime, datetime]]:
    ranges: list[tuple[datetime, datetime]] = []
    buffer = timedelta(minutes=buffer_minutes)
    for event in events:
        if event.get("transparency") == "transparent":
            continue
        bounds = parse_event_bounds(event)
        if not bounds:
            continue
        start, end = bounds
        ranges.append((start - buffer, end + buffer))
    ranges.sort(key=lambda r: r[0])
    return ranges


def _overlaps(
    slot_start: datetime,
    slot_end: datetime,
    busy: list[tuple[datetime, datetime]],
) -> bool:
    for busy_start, busy_end in busy:
        if slot_end <= busy_start or slot_start >= busy_end:
            continue
        return True
    return False


def _day_hour_bounds(time_of_day: Optional[str]) -> tuple[int, int]:
    if time_of_day and time_of_day in TIME_OF_DAY_RANGES:
        return TIME_OF_DAY_RANGES[time_of_day]
    return WORK_START_HOUR, WORK_END_HOUR


def find_free_slots(
    busy_ranges: list[tuple[datetime, datetime]],
    window_start: datetime,
    window_end: datetime,
    duration_minutes: int,
    count: int,
    time_of_day: Optional[str] = None,
) -> list[datetime]:
    """Return up to `count` non-overlapping slot start times spread across days."""
    results: list[datetime] = []
    day = window_start.date()
    end_day = window_end.date()
    duration = timedelta(minutes=duration_minutes)
    step = timedelta(minutes=SLOT_STEP_MINUTES)
    h0, h1 = _day_hour_bounds(time_of_day)
    allowed = [(time(h0, 0), time(h1, 0))]

    while day <= end_day and len(results) < count:
        day_slots: list[datetime] = []
        for range_start, range_end in allowed:
            slot_time = datetime.combine(day, range_start)
            day_end = datetime.combine(day, range_end)

            if day == window_start.date() and slot_time < window_start:
                minutes_past = int((window_start - slot_time).total_seconds() // 60)
                steps = int(minutes_past // SLOT_STEP_MINUTES) + (
                    1 if minutes_past % SLOT_STEP_MINUTES else 0
                )
                slot_time = slot_time + step * steps

            while slot_time + duration <= day_end and len(results) + len(day_slots) < count:
                if slot_time >= window_start and slot_time + duration <= window_end:
                    if not _overlaps(slot_time, slot_time + duration, busy_ranges):
                        day_slots.append(slot_time)
                slot_time += step

        if day_slots:
            results.extend(day_slots[: max(1, count - len(results))])
        day += timedelta(days=1)

    return results[:count]
