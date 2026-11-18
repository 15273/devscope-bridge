"""Filter console and network captures by tab and since_ts.

``since_ts`` is Unix seconds, or milliseconds if the value is >= 10^12.
Console entries use a wall-clock ``ts`` in milliseconds. Network resource
timings often only have a navigation-relative ``startMs``; pass ``wall_ts``
or ``timeOrigin`` so they can be filtered the same way.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

_MS_THRESHOLD = 1_000_000_000_000  # 1e12 — clearly milliseconds since epoch


def normalize_since_ms(since_ts: float | int | None) -> float | None:
    """Convert *since_ts* to milliseconds since epoch, or None if unset."""
    if since_ts is None or since_ts == "":
        return None
    try:
        value = float(since_ts)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    if value >= _MS_THRESHOLD:
        return value
    return value * 1000.0


def _entry_wall_ms(entry: Mapping[str, Any], time_origin_ms: float | None = None) -> float | None:
    for key in ("ts", "wall_ts", "wallTs", "timestamp", "time"):
        if key in entry and entry[key] is not None:
            raw = entry[key]
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            if value >= _MS_THRESHOLD or value > 1_000_000_000:
                # already ms or seconds-sized epoch
                return value if value >= _MS_THRESHOLD else value * 1000.0
            # relative startMs — only useful with time origin
            if time_origin_ms is not None:
                return time_origin_ms + value
    start = entry.get("startMs", entry.get("start_ms"))
    if start is not None and time_origin_ms is not None:
        try:
            return time_origin_ms + float(start)
        except (TypeError, ValueError):
            return None
    return None


def _entry_tab_id(entry: Mapping[str, Any]) -> int | None:
    raw = entry.get("tab_id", entry.get("tabId", entry.get("tab")))
    if raw in (None, ""):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def filter_entries(
    entries: Iterable[Mapping[str, Any]] | None,
    *,
    tab_id: int | None = None,
    since_ts: float | int | None = None,
    time_origin_ms: float | None = None,
) -> list[dict[str, Any]]:
    """Return entries that match an optional tab and a lower bound timestamp."""
    since_ms = normalize_since_ms(since_ts)
    wanted_tab = None if tab_id in (None, "") else int(tab_id)
    out: list[dict[str, Any]] = []
    for raw in entries or []:
        if not isinstance(raw, Mapping):
            continue
        item = dict(raw)
        if wanted_tab is not None:
            entry_tab = _entry_tab_id(item)
            # Entries with no tab id are kept only when they came from a
            # tab-scoped capture (caller should already have scoped them).
            # When a mixed list is filtered, drop unknown-tab rows.
            if entry_tab is not None and entry_tab != wanted_tab:
                continue
            if entry_tab is None and any(_entry_tab_id(e) is not None for e in (entries or [])):
                # mixed list: skip untagged rows
                continue
        if since_ms is not None:
            wall = _entry_wall_ms(item, time_origin_ms)
            if wall is None or wall < since_ms:
                continue
        out.append(item)
    return out


def filter_console(
    payload: Mapping[str, Any] | list | None,
    *,
    tab_id: int | None = None,
    since_ts: float | int | None = None,
) -> dict[str, Any]:
    """Filter a get_console payload (or a bare list of entries)."""
    if isinstance(payload, list):
        entries = payload
        extra: dict[str, Any] = {}
    elif isinstance(payload, Mapping):
        entries = payload.get("entries") or payload.get("logs") or []
        extra = {k: v for k, v in payload.items() if k not in {"entries", "logs", "count"}}
    else:
        entries, extra = [], {}
    filtered = filter_entries(entries, tab_id=tab_id, since_ts=since_ts)
    return {**extra, "count": len(filtered), "entries": filtered}


def filter_network(
    payload: Mapping[str, Any] | list | None,
    *,
    tab_id: int | None = None,
    since_ts: float | int | None = None,
    time_origin_ms: float | None = None,
) -> dict[str, Any]:
    """Filter a get_network payload (or a bare list of resources)."""
    if isinstance(payload, list):
        resources = payload
        extra: dict[str, Any] = {}
        origin = time_origin_ms
    elif isinstance(payload, Mapping):
        resources = payload.get("resources") or payload.get("entries") or payload.get("requests") or []
        extra = {k: v for k, v in payload.items() if k not in {"resources", "entries", "requests", "count"}}
        origin = time_origin_ms
        if origin is None:
            raw_origin = payload.get("timeOrigin") or payload.get("time_origin")
            if raw_origin is not None:
                try:
                    origin = float(raw_origin)
                except (TypeError, ValueError):
                    origin = None
    else:
        resources, extra, origin = [], {}, time_origin_ms
    filtered = filter_entries(resources, tab_id=tab_id, since_ts=since_ts, time_origin_ms=origin)
    return {**extra, "count": len(filtered), "resources": filtered}
