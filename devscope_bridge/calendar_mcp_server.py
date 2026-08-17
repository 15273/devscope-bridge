"""
calendar_mcp_server.py — MCP server exposing Google Calendar read ops.

Claude/Cursor spawns:
  .venv/bin/python -m devscope_bridge.calendar_mcp_server
"""

from __future__ import annotations

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


async def _call(
    method: str,
    path: str,
    params: dict | None = None,
    json_body: dict | None = None,
) -> dict[str, Any]:
    token = _read_token()
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.request(
                method,
                f"{_BRIDGE_URL}{path}",
                params=params,
                json=json_body,
                headers={"Authorization": f"Bearer {token}"},
            )
    except httpx.RequestError as exc:
        return {"ok": False, "error": f"Bridge unreachable: {exc}"}
    if resp.status_code >= 400:
        return {"ok": False, "error": f"HTTP {resp.status_code}", "body": resp.text}
    return resp.json()


mcp = FastMCP(
    "calendar-control",
    instructions=(
        "Google Calendar for DevScope. Token at ~/.dev-bridge/calendar_token.json — "
        "run `python -m devscope_bridge.calendar.authorize_calendar`. "
        "Read: cal_list_events, cal_get_event, cal_find_free_slots. "
        "Write: cal_validate_event_draft then cal_create_event only after the user "
        "explicitly confirmed (user_confirmed=true)."
    ),
)


@mcp.tool()
async def cal_list_events(
    time_min: str | None = None,
    time_max: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """List calendar events in a time range (ISO datetimes). Defaults to next 7 days."""
    params: dict[str, Any] = {"limit": limit}
    if time_min:
        params["time_min"] = time_min
    if time_max:
        params["time_max"] = time_max
    return await _call("GET", "/cal/events", params=params)


@mcp.tool()
async def cal_get_event(event_id: str) -> dict[str, Any]:
    """Fetch a single calendar event by ID."""
    return await _call("GET", "/cal/event", params={"event_id": event_id})


@mcp.tool()
async def cal_find_free_slots(
    duration_minutes: int = 30,
    days_ahead: int = 7,
    count: int = 5,
    time_of_day: str | None = None,
) -> dict[str, Any]:
    """Suggest free meeting slots during work hours (morning|afternoon|evening optional)."""
    params: dict[str, Any] = {
        "duration_minutes": duration_minutes,
        "days_ahead": days_ahead,
        "count": count,
    }
    if time_of_day:
        params["time_of_day"] = time_of_day
    return await _call("GET", "/cal/free-slots", params=params)


@mcp.tool()
async def cal_validate_event_draft(
    summary: str,
    start: str,
    end: str,
    description: str = "",
    location: str = "",
    attendees: list[str] | None = None,
    add_google_meet: bool = False,
) -> dict[str, Any]:
    """Validate an event draft (ISO start/end). Does not create anything."""
    payload = {
        "summary": summary,
        "start": start,
        "end": end,
        "description": description,
        "location": location,
        "attendees": attendees or [],
        "add_google_meet": add_google_meet,
    }
    return await _call("POST", "/cal/draft", json_body=payload)


@mcp.tool()
async def cal_create_event(
    summary: str,
    start: str,
    end: str,
    description: str = "",
    location: str = "",
    attendees: list[str] | None = None,
    add_google_meet: bool = False,
    user_confirmed: bool = False,
) -> dict[str, Any]:
    """Create a calendar event. Requires user_confirmed=true after explicit user approval."""
    if not user_confirmed:
        return {
            "ok": False,
            "error": "Refused: set user_confirmed=true only after the user explicitly approved.",
        }
    payload = {
        "summary": summary,
        "start": start,
        "end": end,
        "description": description,
        "location": location,
        "attendees": attendees or [],
        "add_google_meet": add_google_meet,
    }
    return await _call("POST", "/cal/events/create", json_body=payload)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    mcp.run(transport="stdio")
