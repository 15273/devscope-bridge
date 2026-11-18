"""Token-auth CDP fallback when the DevScope side panel is not connected.

The extension WebSocket is the preferred path: it has snapshot refs, the
console buffer, and full tool coverage. When no WS is up, a client that
already passed loopback token auth can still drive a *loopback* Chrome
CDP port (daily or QA) for a documented subset of tools.

This module never prints CDP or bridge tokens. Endpoints must be loopback.
Service workers are selected with :func:`pick_service_worker`, never ``[0]``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from typing import Any

import httpx

from devscope_bridge.browser_filters import filter_console, filter_network
from devscope_bridge.log_redact import redact_url_query
from devscope_bridge.browser_profiles import (
    CDP_FALLBACK_TOOLS,
    BrowserProfile,
    get_profile,
    load_profiles,
)
from devscope_bridge.service_workers import (
    DEFAULT_DEVSCOPE_EXTENSION_ID,
    pick_service_worker,
)

logger = logging.getLogger(__name__)

_CDP_HTTP_TIMEOUT_S = 1.5


def configured_extension_id() -> str:
    return os.environ.get("DEVSCOPE_EXTENSION_ID") or DEFAULT_DEVSCOPE_EXTENSION_ID


def pick_page_target(targets: list[dict[str, Any]], tab_id: int | str | None = None) -> dict[str, Any] | None:
    """Pick a page/tab target. Never returns a service worker or ``targets[0]`` blindly."""
    pages = [
        t for t in targets
        if str(t.get("type") or "").lower() in {"page", "iframe", "tab"}
        and not str(t.get("url") or "").startswith(("chrome://", "devtools://", "chrome-extension://"))
    ]
    if not pages:
        pages = [
            t for t in targets
            if str(t.get("type") or "").lower() in {"page", "tab"}
        ]
    if tab_id in (None, ""):
        # Prefer the one marked "webSocketDebuggerUrl" that is a page, last focused
        # if Chrome included "lastActive" or similar; otherwise the first *page*.
        return pages[0] if pages else None
    wanted = str(tab_id)
    for t in pages:
        if str(t.get("id") or "") == wanted:
            return t
        # Chrome tab ids from the extension are integers; CDP uses a uuid.
        # Also accept a numeric "tabId" if present, or a suffix match.
        if str(t.get("tabId") or t.get("tab_id") or "") == wanted:
            return t
    return None


async def fetch_targets(hostport: str, timeout: float = _CDP_HTTP_TIMEOUT_S) -> list[dict[str, Any]]:
    """GET /json/list from a loopback CDP endpoint."""
    url = f"http://{hostport}/json/list"
    async with httpx.AsyncClient() as client:
        response = await client.get(url, timeout=timeout)
        response.raise_for_status()
        data = response.json()
    if not isinstance(data, list):
        return []
    return [t for t in data if isinstance(t, dict)]


async def cdp_available(hostport: str, timeout: float = 0.6) -> bool:
    try:
        url = f"http://{hostport}/json/version"
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=timeout)
            return response.status_code == 200
    except Exception:
        return False


def tabs_from_targets(
    targets: list[dict[str, Any]],
    *,
    profile: str = "",
) -> list[dict[str, Any]]:
    tabs: list[dict[str, Any]] = []
    for t in targets:
        typ = str(t.get("type") or "").lower()
        if typ not in {"page", "tab"}:
            continue
        url = str(t.get("url") or "")
        if url.startswith(("devtools://",)):
            continue
        tabs.append({
            "id": t.get("id"),
            "title": t.get("title") or "",
            "url": redact_url_query(url),
            "type": typ,
            "profile": profile,
        })
    return tabs


async def list_tabs_for_profile(profile: BrowserProfile, timeout: float = _CDP_HTTP_TIMEOUT_S) -> list[dict[str, Any]]:
    try:
        targets = await fetch_targets(profile.cdp, timeout=timeout)
    except Exception as exc:
        logger.info("CDP list_tabs failed for profile %s: %s", profile.name, exc)
        return []
    return tabs_from_targets(targets, profile=profile.name)


async def profile_health_snapshot(
    extensions: list[dict[str, Any]] | None = None,
    timeout: float = 0.5,
) -> list[dict[str, Any]]:
    """Health rows for every named profile: CDP reachability + extension WS."""
    ext_labels = {
        (e.get("profile_id") or e.get("profile_label") or e.get("session") or "").lower()
        for e in (extensions or [])
    }
    ext_names = {e.get("profile_label") or "" for e in (extensions or [])}
    rows: list[dict[str, Any]] = []
    for profile in load_profiles(include_default_daily=True):
        ok = await cdp_available(profile.cdp, timeout=timeout)
        tabs: list[dict[str, Any]] = []
        if ok:
            try:
                tabs = await list_tabs_for_profile(profile, timeout=timeout)
            except Exception:
                tabs = []
        ext_connected = (
            profile.name.lower() in ext_labels
            or profile.display_label() in ext_names
            or any(profile.name.lower() in (e.get("profile_label") or "").lower() for e in (extensions or []))
        )
        rows.append({
            "name": profile.name,
            "label": profile.display_label(),
            "cdp": profile.cdp,
            "cdp_ok": ok,
            "extension_connected": ext_connected,
            "tabs": len(tabs),
        })
    return rows


async def _cdp_command(ws_url: str, method: str, params: dict[str, Any] | None = None, timeout: float = 8.0) -> dict[str, Any]:
    """Send one CDP command on a fresh websocket and return the result.

    Imported lazily so unit tests can monkeypatch this without opening sockets.
    """
    import websockets

    payload = {"id": 1, "method": method, "params": params or {}}
    async with websockets.connect(ws_url, open_timeout=timeout, close_timeout=1, max_size=20_000_000) as ws:
        await ws.send(json.dumps(payload))
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
            frame = json.loads(raw)
            if frame.get("id") == 1:
                if "error" in frame:
                    raise RuntimeError(frame["error"].get("message") or str(frame["error"]))
                return frame.get("result") or {}


async def _runtime_evaluate(ws_url: str, expression: str, timeout: float = 8.0) -> Any:
    result = await _cdp_command(
        ws_url,
        "Runtime.evaluate",
        {"expression": expression, "returnByValue": True, "awaitPromise": True},
        timeout=timeout,
    )
    if result.get("exceptionDetails"):
        detail = result["exceptionDetails"]
        text = detail.get("text") or detail.get("exception", {}).get("description") or "evaluate failed"
        raise RuntimeError(text)
    return (result.get("result") or {}).get("value")


def _ws_url_for(target: dict[str, Any]) -> str:
    ws_url = target.get("webSocketDebuggerUrl") or target.get("webSocketDebuggerUrl".lower())
    if not ws_url:
        raise RuntimeError("CDP target has no webSocketDebuggerUrl")
    return str(ws_url)


async def run_cdp_action(
    tool: str,
    args: dict[str, Any],
    *,
    profile_name: str | None = None,
) -> dict[str, Any]:
    """Run a supported tool over CDP. Raises ValueError for unsupported tools."""
    if tool not in CDP_FALLBACK_TOOLS:
        raise ValueError(f"{tool} is not available via the CDP fallback; open the DevScope side panel")

    profile = get_profile(profile_name) if profile_name else None
    if profile is None:
        # Prefer a reachable profile; try named ones in order (daily, qa, ...)
        for candidate in load_profiles(include_default_daily=False):
            if await cdp_available(candidate.cdp):
                profile = candidate
                break
    if profile is None:
        raise RuntimeError("No reachable loopback CDP endpoint (set DEVSCOPE_CDP_ENDPOINTS)")

    targets = await fetch_targets(profile.cdp)
    tab_id = args.get("tab_id", args.get("tabId", args.get("tab")))
    since_ts = args.get("since_ts", args.get("sinceTs"))

    if tool == "browser_list_tabs":
        # Also surface the DevScope SW (matched by id, never [0]) so health can
        # tell whether the extension is loaded even if the panel is closed.
        sw = pick_service_worker(targets, configured_extension_id())
        data = {
            "tabs": tabs_from_targets(targets, profile=profile.name),
            "profile": profile.name,
            "extension_service_worker": (
                {"url": redact_url_query(str(sw.get("url") or "")), "id": sw.get("id")}
                if sw else None
            ),
        }
        return {"ok": True, "data": data, "error": None, "via": "cdp", "profile": profile.name}

    page = pick_page_target(targets, tab_id)
    if page is None:
        return {"ok": False, "data": None, "error": "No page target on this CDP endpoint", "via": "cdp", "profile": profile.name}
    ws_url = _ws_url_for(page)

    if tool == "browser_get_page_info":
        data = {
            "tabId": page.get("id"),
            "url": redact_url_query(str(page.get("url") or "")),
            "title": page.get("title") or "",
            "profile": profile.name,
        }
        return {"ok": True, "data": data, "error": None, "via": "cdp", "profile": profile.name}

    if tool == "browser_navigate":
        url = str(args.get("url") or "")
        if not url:
            return {"ok": False, "data": None, "error": "url is required", "via": "cdp", "profile": profile.name}
        await _cdp_command(ws_url, "Page.navigate", {"url": url})
        return {"ok": True, "data": {"url": redact_url_query(url)}, "error": None, "via": "cdp", "profile": profile.name}

    if tool == "browser_evaluate":
        expression = str(args.get("expression") or "")
        if not expression:
            return {"ok": False, "data": None, "error": "expression is required", "via": "cdp", "profile": profile.name}
        value = await _runtime_evaluate(ws_url, expression)
        return {"ok": True, "data": {"value": value}, "error": None, "via": "cdp", "profile": profile.name}

    if tool == "browser_screenshot":
        result = await _cdp_command(ws_url, "Page.captureScreenshot", {"format": "png"})
        return {"ok": True, "data": {"data": result.get("data"), "format": "png"}, "error": None, "via": "cdp", "profile": profile.name}

    if tool in {"browser_get_console", "browser_get_network"}:
        # Read in-page buffers / performance entries. Console is empty until a
        # previous session installed the DevScope hook; we still return a
        # well-shaped, tab- and since_ts-filtered payload.
        if tool == "browser_get_console":
            raw = await _runtime_evaluate(
                ws_url,
                "({entries: (window.__devscopeConsole||[]).slice(), timeOrigin: performance.timeOrigin})",
            ) or {}
            max_n = int(args.get("max") or 100)
            payload = filter_console(raw, tab_id=None, since_ts=since_ts)
            payload["entries"] = payload["entries"][-max_n:]
            payload["count"] = len(payload["entries"])
            payload["tab_id"] = page.get("id")
            return {"ok": True, "data": payload, "error": None, "via": "cdp", "profile": profile.name}
        raw = await _runtime_evaluate(
            ws_url,
            """(() => {
              const origin = performance.timeOrigin;
              const resources = performance.getEntriesByType('resource').slice(-150).map((e) => ({
                name: e.name, type: e.initiatorType,
                durationMs: Math.round(e.duration),
                transferSize: e.transferSize,
                startMs: Math.round(e.startTime),
                wall_ts: origin + e.startTime,
              }));
              return { url: location.href, timeOrigin: origin, resources };
            })()""",
        ) or {}
        payload = filter_network(raw, tab_id=None, since_ts=since_ts)
        payload["tab_id"] = page.get("id")
        return {"ok": True, "data": payload, "error": None, "via": "cdp", "profile": profile.name}

    if tool in {"browser_click", "browser_fill", "browser_assert_text", "browser_wait_for_selector"}:
        selector = str(args.get("selector") or "")
        if tool != "browser_assert_text" and not selector:
            return {"ok": False, "data": None, "error": "selector is required", "via": "cdp", "profile": profile.name}
        if tool == "browser_click":
            expr = f"""(() => {{ const el = document.querySelector({json.dumps(selector)}); if (!el) return {{error: 'not found'}}; el.click(); return {{clicked: true}}; }})()"""
        elif tool == "browser_fill":
            value = str(args.get("value") or "")
            expr = f"""(() => {{ const el = document.querySelector({json.dumps(selector)}); if (!el) return {{error: 'not found'}}; el.focus(); el.value = {json.dumps(value)}; el.dispatchEvent(new Event('input', {{bubbles: true}})); el.dispatchEvent(new Event('change', {{bubbles: true}})); return {{filled: true}}; }})()"""
        elif tool == "browser_assert_text":
            text = str(args.get("text") or "")
            sel_js = json.dumps(selector or None)
            expr = f"""(() => {{ const sel = {sel_js}; const scope = sel ? document.querySelector(sel) : document.body; if (sel && !scope) return {{present: false, error: 'Element not found: ' + sel}}; const present = (scope && (scope.textContent||'').includes({json.dumps(text)})); return {{present}}; }})()"""
        else:
            timeout_ms = int(args.get("timeout_ms") or 5000)
            expr = f"""(() => new Promise((resolve) => {{
              const sel = {json.dumps(selector)};
              const start = Date.now();
              const tick = () => {{
                if (document.querySelector(sel)) return resolve({{found: true}});
                if (Date.now() - start > {timeout_ms}) return resolve({{found: false}});
                setTimeout(tick, 100);
              }};
              tick();
            }}))()"""
        value = await _runtime_evaluate(ws_url, expr)
        if isinstance(value, dict) and value.get("error"):
            return {"ok": False, "data": value, "error": str(value["error"]), "via": "cdp", "profile": profile.name}
        if tool == "browser_assert_text" and isinstance(value, dict) and not value.get("present"):
            return {"ok": False, "data": value, "error": "text not found", "via": "cdp", "profile": profile.name}
        if tool == "browser_wait_for_selector" and isinstance(value, dict) and not value.get("found"):
            return {"ok": False, "data": value, "error": "selector not found", "via": "cdp", "profile": profile.name}
        return {"ok": True, "data": value, "error": None, "via": "cdp", "profile": profile.name}

    raise ValueError(f"{tool} is not available via the CDP fallback")
