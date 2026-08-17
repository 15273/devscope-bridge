"""
browser_relay.py — Bridge relay state and /actions handler.

Owns:
- _pending_actions: action_id → asyncio.Future[BrowserResult]
- _action_session:  action_id → session_name (dispatching WS, for the disconnect sweep)
- _active_ws:       session_name → active WebSocket
- _ws_profile:      session_name → {profile_id, profile_label} (Chrome profile behind the WS)
- _tab_profile:     tab_id → profile_id (learned from list_tabs fan-out, for routing)
- resolve_browser_result(): called by the WS receive loop on browser_result frames
- fail_pending_for_session(): called on WS disconnect to fail its in-flight actions immediately
- post_action():    FastAPI handler for POST /actions

Every browser tool_call MUST resolve — success or error, never hang forever —
via two independent nets: a per-action deadline (`_action_timeout_s`) and a
disconnect sweep (`fail_pending_for_session`, fired by `deregister_ws`) that
fails in-flight actions the instant their WS drops. A browser_result arriving
after either already resolved the action is a no-op (`future.done()` guard).

Cross-profile routing
---------------------
DevScope is installed in every Chrome profile, and each profile's offscreen
document opens its own WS to this bridge. The bridge therefore holds a WS for
every connected profile. `browser_list_tabs` fans out to one WS per profile and
aggregates the results, so an agent sees ALL profiles' tabs. Actions that target
a specific tab_id are routed to the WS of the profile that owns that tab (learned
from the last list_tabs), so the agent can drive tabs in any profile — without
opening new windows or using OS-level computer control.
"""

import asyncio
import logging
import uuid
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel

from devscope_bridge.models import BrowserResult, ToolCall

logger = logging.getLogger(__name__)

# Per-action deadline: how long `_send_action` waits for a browser_result
# before giving up on the extension and resolving ok=False itself. Screenshots
# and snapshots get a shorter cap since a stuck capture is cheap to detect;
# everything else defaults to the longer window (page loads, ATS fills, etc.).
_DEFAULT_ACTION_TIMEOUT_S = 60.0
_ACTION_TIMEOUT_OVERRIDES_S: dict[str, float] = {
    "browser_screenshot": 30.0,
    "browser_snapshot": 30.0,
}


def _action_timeout_s(tool: str) -> float:
    """Deadline in seconds for a given tool — override map, else the default."""
    return _ACTION_TIMEOUT_OVERRIDES_S.get(tool, _DEFAULT_ACTION_TIMEOUT_S)


# action_id → asyncio.Future[BrowserResult]
_pending_actions: dict[str, asyncio.Future] = {}

# action_id → session_name that dispatched it (drives the disconnect sweep)
_action_session: dict[str, str] = {}

# session_name → active WebSocket (any object with async send_text)
_active_ws: dict[str, Any] = {}

# session_name → {"profile_id": str, "profile_label": str}
_ws_profile: dict[str, dict[str, str]] = {}

# tab_id → profile_id  (learned from browser_list_tabs fan-out; drives routing)
_tab_profile: dict[int, str] = {}


# ─────────────────────────────────────────────
# WS registry helpers
# ─────────────────────────────────────────────

def register_ws(session_name: str, ws: Any) -> None:
    _active_ws[session_name] = ws


def deregister_ws(session_name: str, ws: Any) -> None:
    """Remove the registry entry only if it still points at THIS ws.

    A1 fix (RC-4): on a fast reconnect, the NEW WS's register_ws may already
    have replaced the entry by the time the OLD connection's cleanup runs —
    deregistering unconditionally by name would then evict the new socket
    instead of the stale one.
    """
    if _active_ws.get(session_name) is ws:
        _active_ws.pop(session_name, None)
        _ws_profile.pop(session_name, None)
        fail_pending_for_session(session_name)


def has_active_ws(session_name: str) -> bool:
    return session_name in _active_ws


def first_active_session() -> str | None:
    return next(iter(_active_ws), None)


async def broadcast_text(text: str) -> None:
    """Send a JSON frame to every connected session WS (task board live updates)."""
    dead: list[str] = []
    for session_name, ws in list(_active_ws.items()):
        try:
            await ws.send_text(text)
        except Exception:
            dead.append(session_name)
    for name in dead:
        _active_ws.pop(name, None)
        _ws_profile.pop(name, None)


def candidate_sessions() -> list[str]:
    """One representative active session per connected Chrome profile.

    Lets callers (e.g. the cockpit poller) try each profile in turn, since the
    WhatsApp tab may live in any one of several connected profiles.
    """
    return list(_one_session_per_profile().values())


def connection_summary() -> dict[str, Any]:
    """Lightweight status for /capabilities (extension Settings)."""
    profiles = list(_ws_profile.values())
    return {
        "connected_sessions": len(_active_ws),
        "connected_profiles": len(profiles),
        "profiles": [
            {"id": p.get("profile_id", ""), "label": p.get("profile_label", "")}
            for p in profiles
        ],
    }


def set_ws_profile(session_name: str, profile_id: str, profile_label: str) -> None:
    """Record which Chrome profile is behind a session's WS (from the hello frame)."""
    prev = _ws_profile.get(session_name)
    next_meta = {
        "profile_id": profile_id,
        "profile_label": profile_label or profile_id,
    }
    if prev == next_meta:
        return
    _ws_profile[session_name] = next_meta
    logger.debug(
        "WS profile registered: session='%s' profile='%s' (%s)",
        session_name, profile_label, profile_id,
    )


def _profile_of(session_name: str) -> str:
    """Profile id for a session; falls back to the session name when unknown."""
    meta = _ws_profile.get(session_name)
    return meta["profile_id"] if meta else f"session:{session_name}"


def _one_session_per_profile() -> dict[str, str]:
    """Map profile_id → a representative active session (one WS per profile)."""
    chosen: dict[str, str] = {}
    for session_name in _active_ws:
        pid = _profile_of(session_name)
        chosen.setdefault(pid, session_name)
    return chosen


def _session_for_profile(profile_id: str) -> str | None:
    """An active session whose WS belongs to the given profile."""
    for session_name in _active_ws:
        if _profile_of(session_name) == profile_id:
            return session_name
    return None


# ─────────────────────────────────────────────
# browser_result resolution
# ─────────────────────────────────────────────

def resolve_browser_result(data: dict) -> None:
    """Resolve a pending Future when the extension sends a browser_result frame.

    A late frame (action already timed out, swept on disconnect, or already
    popped from `_pending_actions`) is a safe no-op — never raises.
    """
    action_id = data.get("action_id", "")
    future = _pending_actions.get(action_id)
    if future is None:
        logger.debug("browser_result for unknown/already-resolved action_id '%s' — dropped", action_id)
        return
    if future.done():
        logger.debug("browser_result for already-resolved action_id '%s' — dropped", action_id)
        return
    try:
        result = BrowserResult(**data)
        future.set_result(result)
    except Exception as exc:
        future.set_exception(exc)


def fail_pending_for_session(session_name: str) -> None:
    """Immediately fail every action dispatched over a session's WS.

    Called on WS disconnect (e.g. the extension reloaded mid-action) so an
    in-flight action doesn't sit waiting out its full deadline. `_send_action`'s
    own `finally` block removes the bookkeeping entries once it wakes up.
    """
    stale_action_ids = [
        action_id for action_id, sess in _action_session.items() if sess == session_name
    ]
    for action_id in stale_action_ids:
        future = _pending_actions.get(action_id)
        if future is not None and not future.done():
            future.set_result(
                BrowserResult(
                    action_id=action_id, ok=False, data=None,
                    error="extension_disconnected",
                )
            )


# ─────────────────────────────────────────────
# Low-level send-and-wait
# ─────────────────────────────────────────────

async def _send_action(
    session_name: str,
    tool: str,
    args: dict[str, Any],
    *,
    quiet: bool = False,
) -> BrowserResult:
    """Send one tool_call to a session's WS and await its browser_result.

    Always resolves — never hangs — via the per-tool deadline below plus the
    disconnect sweep in `fail_pending_for_session` (see module docstring).
    """
    if not has_active_ws(session_name):
        raise HTTPException(status_code=503, detail="Browser client not connected")

    action_id = str(uuid.uuid4())
    frame = ToolCall(
        action_id=action_id, tool=tool, args=args, session=session_name, quiet=quiet,
    )

    loop = asyncio.get_event_loop()
    future: asyncio.Future = loop.create_future()
    _pending_actions[action_id] = future
    _action_session[action_id] = session_name

    ws = _active_ws[session_name]
    try:
        await ws.send_text(frame.model_dump_json())
    except Exception as exc:
        _pending_actions.pop(action_id, None)
        _action_session.pop(action_id, None)
        logger.warning("Failed to send tool_call to WS session '%s': %s", session_name, exc)
        raise HTTPException(status_code=503, detail="Browser client not connected")

    timeout_s = _action_timeout_s(tool)
    try:
        return await asyncio.wait_for(future, timeout=timeout_s)
    except asyncio.TimeoutError:
        logger.warning(
            "Browser action '%s' (id=%s, session=%s) timed out after %.0fs — "
            "resolving ok=False instead of hanging",
            tool, action_id, session_name, timeout_s,
        )
        return BrowserResult(
            action_id=action_id,
            ok=False,
            data=None,
            error=f"timeout: extension did not answer within {timeout_s:.0f}s",
        )
    finally:
        _pending_actions.pop(action_id, None)
        _action_session.pop(action_id, None)


def _learn_tab_profiles(tabs: list[dict], profile_id: str) -> None:
    """Remember which profile each tab_id lives in, for later action routing."""
    for tab in tabs:
        tab_id = tab.get("id")
        if isinstance(tab_id, int):
            _tab_profile[tab_id] = profile_id


# ─────────────────────────────────────────────
# Cross-profile list_tabs (fan-out)
# ─────────────────────────────────────────────

async def _list_tabs_all_profiles() -> dict[str, Any]:
    """Fan out browser_list_tabs to one WS per profile and aggregate the tabs."""
    per_profile = _one_session_per_profile()
    all_tabs: list[dict] = []
    all_windows: list[dict] = []
    profiles: list[dict] = []

    async def _query(profile_id: str, session_name: str) -> None:
        meta = _ws_profile.get(session_name, {})
        label = meta.get("profile_label", profile_id)
        try:
            result = await _send_action(session_name, "browser_list_tabs", {})
        except HTTPException:
            return
        if not result.ok or not isinstance(result.data, dict):
            return
        tabs = result.data.get("tabs") or []
        windows = result.data.get("windows") or []
        _learn_tab_profiles(tabs, profile_id)
        for tab in tabs:
            tab["profile_id"] = profile_id
            tab["profile_label"] = label
            all_tabs.append(tab)
        for win in windows:
            win["profile_id"] = profile_id
            all_windows.append(win)
        profiles.append({
            "profile_id": profile_id,
            "profile_label": label,
            "tab_count": len(tabs),
        })

    await asyncio.gather(*[
        _query(pid, sess) for pid, sess in per_profile.items()
    ])

    return {
        "tabs": all_tabs,
        "windows": all_windows,
        "profiles": profiles,
        "total_tabs": len(all_tabs),
        "total_profiles": len(profiles),
        "note": (
            "Tabs across ALL connected Chrome profiles. Each tab carries profile_id "
            "and profile_label. To drive a tab in another profile, pass its tab_id — "
            "the bridge routes the action to the profile that owns it. Profiles only "
            "appear here once a DevScope panel has been opened in them at least once."
        ),
    }


# ─────────────────────────────────────────────
# /actions endpoint
# ─────────────────────────────────────────────

class ActionRequest(BaseModel):
    tool: str
    args: dict[str, Any] = {}
    session: str | None = None
    quiet: bool = False


def _target_session(tool: str, args: dict[str, Any], requesting: str) -> str:
    """Pick the WS session to run an action on, honoring cross-profile tab routing."""
    raw = args.get("tab_id", args.get("tabId"))
    if raw not in (None, ""):
        try:
            tab_id = int(raw)
        except (TypeError, ValueError):
            tab_id = None
        if tab_id is not None:
            owner_profile = _tab_profile.get(tab_id)
            if owner_profile and owner_profile != _profile_of(requesting):
                routed = _session_for_profile(owner_profile)
                if routed:
                    return routed
    return requesting


async def post_action(body: ActionRequest, auth: None) -> dict:
    """Forward a browser tool call to the Chrome extension via the active WS."""
    requesting = body.session or first_active_session()
    if requesting is None or not has_active_ws(requesting):
        connected = list(_active_ws.keys())
        raise HTTPException(
            status_code=503,
            detail=(
                f"Browser client not connected (session={body.session!r}, "
                f"connected={connected}). Reload DevScope unpacked from "
                "extension/dist or open the side panel."
            ),
        )

    # browser_list_tabs aggregates across every connected profile.
    if body.tool == "browser_list_tabs":
        return {"ok": True, "data": await _list_tabs_all_profiles(), "error": None}

    target = _target_session(body.tool, body.args, requesting)
    result = await _send_action(target, body.tool, body.args, quiet=body.quiet)
    return {"ok": result.ok, "data": result.data, "error": result.error}
