"""calendar_routes.py — FastAPI /cal/* router over the Calendar service."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from devscope_bridge.calendar import calendar_service

router = APIRouter(prefix="/cal", tags=["calendar"])


class EventDraftBody(BaseModel):
    summary: str
    start: str
    end: str
    description: str = ""
    location: str = ""
    attendees: list[str] = Field(default_factory=list)
    add_google_meet: bool = False


@router.get("/health")
async def health() -> dict:
    return {
        "ok": True,
        "data": {
            "token_configured": calendar_service.token_configured(),
            "can_write": calendar_service.token_can_write(),
        },
    }


@router.get("/events")
async def events(
    time_min: str | None = Query(None, description="ISO datetime start"),
    time_max: str | None = Query(None, description="ISO datetime end"),
    limit: int = 50,
    calendar_id: str = "primary",
) -> dict:
    t_min = datetime.fromisoformat(time_min) if time_min else None
    t_max = datetime.fromisoformat(time_max) if time_max else None
    return await calendar_service.list_events(
        t_min, t_max, calendar_id=calendar_id, limit=limit,
    )


@router.get("/event")
async def event(
    event_id: str,
    calendar_id: str = "primary",
) -> dict:
    return await calendar_service.get_event(event_id, calendar_id=calendar_id)


@router.get("/free-slots")
async def free_slots(
    duration_minutes: int = 30,
    days_ahead: int = 7,
    count: int = 5,
    time_of_day: str | None = Query(None, pattern="^(morning|afternoon|evening)$"),
    calendar_id: str = "primary",
) -> dict:
    return await calendar_service.suggest_free_slots(
        duration_minutes=duration_minutes,
        days_ahead=days_ahead,
        count=count,
        time_of_day=time_of_day,
        calendar_id=calendar_id,
    )


@router.post("/draft")
async def validate_draft(body: EventDraftBody) -> dict:
    """Validate an event draft without creating it."""
    return await calendar_service.validate_event_draft(body.model_dump())


@router.post("/events/create")
async def create_event(body: EventDraftBody) -> dict:
    """Create a calendar event (UI must confirm before calling)."""
    return await calendar_service.create_event(body.model_dump())
