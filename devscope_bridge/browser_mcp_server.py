"""
browser_mcp_server.py — MCP server (stdio) that forwards browser tool calls
to the Dev Bridge over loopback HTTP.

Claude CLI spawns this as a child process:
  .venv/bin/python -m devscope_bridge.browser_mcp_server

When Claude calls a browser tool, this server:
1. Reads the bridge token from ~/.dev-bridge/token.
2. POSTs {tool, args, session} to http://127.0.0.1:7878/actions.
3. Returns the BrowserResult payload to Claude as the tool result.

End-to-end won't work until the Chrome extension is connected (Day 4).
The bridge will return 503 "Browser client not connected" until then.
"""

import base64
import json
import logging
import mimetypes
import os
from pathlib import Path
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────

_TOKEN_FILE = Path.home() / ".dev-bridge" / "token"
_BRIDGE_URL = os.environ.get("BRIDGE_URL", "http://127.0.0.1:7878")

TOOL_NAMES = [
    "browser_navigate",
    "browser_screenshot",
    "browser_get_page_info",
    "browser_list_tabs",
    "browser_focus_tab",
    "browser_click",
    "browser_fill",
    "browser_get_elements",
    "browser_evaluate",
    "browser_snapshot",
    "browser_get_network",
    "browser_get_console",
    # v2 additions
    "browser_highlight",
    "browser_wait_for_selector",
    "browser_wait_for_navigation",
    "browser_assert_text",
    "browser_scroll_to",
    "browser_select_option",
    "browser_hover",
    "browser_key_press",
    "browser_new_page",
    "browser_upload_file",
    "linkedin_scrape_feed",
    "linkedin_fill_composer",
    "linkedin_fill_comment",
    "linkedin_scrape_people_search",
    "linkedin_read_search_state",
    "linkedin_scrape_profile",
]


def _assert_loopback_bridge_url(url: str) -> None:
    """Reject any BRIDGE_URL that doesn't target loopback."""
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
    """Read the bridge auth token written by main.py at startup."""
    if not _TOKEN_FILE.exists():
        raise RuntimeError(
            f"Bridge token not found at {_TOKEN_FILE}. "
            "Start the Dev Bridge first: python -m devscope_bridge.main"
        )
    return _TOKEN_FILE.read_text().strip()


# ─────────────────────────────────────────────
# Bridge forwarding helper
# ─────────────────────────────────────────────

def _bridge_session() -> str | None:
    """Session name from the Claude subprocess env (set by session_manager)."""
    return os.environ.get("DEVSCOPE_SESSION") or None


async def _forward_to_bridge(
    tool: str,
    args: dict[str, Any],
    timeout: float = 30.0,
) -> dict[str, Any]:
    """
    POST {tool, args, session?} to the bridge /actions endpoint.

    Returns the parsed JSON body from the bridge.
    On HTTP errors, returns {ok: False, error: <message>}.
    """
    token = _read_token()
    payload: dict[str, Any] = {"tool": tool, "args": args}
    session = _bridge_session()
    if session:
        payload["session"] = session
    elif tool.startswith("browser_"):
        logger.warning(
            "browser MCP tool %s without DEVSCOPE_SESSION — extension routing may fail",
            tool,
        )

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{_BRIDGE_URL}/actions",
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
            )
    except httpx.TimeoutException:
        logger.warning("Bridge request timed out for tool '%s'", tool)
        return {"ok": False, "error": "Bridge request timed out"}
    except httpx.RequestError as exc:
        logger.warning("Bridge request error for tool '%s': %s", tool, exc)
        return {"ok": False, "error": f"Bridge unreachable: {exc}"}

    if resp.status_code in (503, 504):
        body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        return {"ok": False, "error": body.get("detail", f"HTTP {resp.status_code}")}

    if resp.status_code != 200:
        return {"ok": False, "error": f"Bridge returned HTTP {resp.status_code}"}

    return resp.json()


def _tab_kwargs(tab_id: int | None) -> dict[str, Any]:
    """Optional tab_id — omit to use the session-bound tab from DevScope UI."""
    return {"tab_id": tab_id} if tab_id is not None else {}


# ─────────────────────────────────────────────
# MCP server + tools
# ─────────────────────────────────────────────

mcp = FastMCP(
    "browser-control",
    instructions=(
        "Forward browser actions to the DevScope Chrome extension via the local bridge. "
        "The bridge must be running (python -m devscope_bridge.main) and the "
        "Chrome extension must be connected for tools to succeed. "
        "Each chat session can bind a browser tab in the DevScope panel — OMIT tab_id "
        "on all tools to use that bound tab (preferred). browser_list_tabs returns "
        "ALL Chrome windows and tabs (not only the focused window). bound_tab_id and "
        "is_bound mark the session target. browser_new_page opens a BACKGROUND tab by "
        "default (pass active=true only if the user must see it). browser_focus_tab "
        "steals user focus — avoid unless explicitly requested. Screenshots briefly "
        "focus the agent tab then restore the user's previous tab."
    ),
)


@mcp.tool()
async def browser_navigate(url: str, tab_id: int | None = None) -> dict[str, Any]:
    """Navigate a tab to a URL. Pass tab_id from browser_list_tabs, or omit for the active tab."""
    return await _forward_to_bridge("browser_navigate", {"url": url, **_tab_kwargs(tab_id)})


@mcp.tool()
async def browser_screenshot(
    selector: str | None = None,
    full_page: bool = False,
    tab_id: int | None = None,
) -> dict[str, Any]:
    """Capture a screenshot of the page or a specific element."""
    args: dict[str, Any] = {"full_page": full_page, **_tab_kwargs(tab_id)}
    if selector is not None:
        args["selector"] = selector
    return await _forward_to_bridge("browser_screenshot", args)


@mcp.tool()
async def browser_get_page_info(tab_id: int | None = None) -> dict[str, Any]:
    """Return URL, title, viewport size and scroll position for a tab."""
    return await _forward_to_bridge("browser_get_page_info", _tab_kwargs(tab_id))


@mcp.tool()
async def browser_list_tabs() -> dict[str, Any]:
    """List open tabs across ALL Chrome windows AND ALL connected Chrome profiles.

    Each tab includes id, url, title, windowId, profile_id, profile_label, is_bound.
    To drive a tab that lives in a different Chrome profile, just pass its tab_id to
    any browser tool — the bridge routes the action to the profile that owns it
    (no new window, no OS-level control needed). A profile only appears here once a
    DevScope panel has been opened in it at least once (that connects its bridge WS)."""
    return await _forward_to_bridge("browser_list_tabs", {})


@mcp.tool()
async def browser_focus_tab(tab_id: int | None = None) -> dict[str, Any]:
    """Focus the Chrome window and tab. Omit tab_id to focus the session-bound tab."""
    return await _forward_to_bridge("browser_focus_tab", _tab_kwargs(tab_id))


@mcp.tool()
async def browser_new_page(
    url: str = "about:blank",
    window_id: int | None = None,
    active: bool = False,
) -> dict[str, Any]:
    """Open a new tab in an existing Chrome window (defaults to the focused window).
    By default opens in the BACKGROUND (active=false) so the user can keep working.
    Use browser_new_page + bind that tab_id for automation without stealing focus.
    Pass active=true only when the user must see the new page immediately."""
    payload: dict[str, Any] = {"url": url, "active": active}
    if window_id is not None:
        payload["window_id"] = window_id
    return await _forward_to_bridge("browser_new_page", payload)


@mcp.tool()
async def browser_click(
    selector: str = "",
    tab_id: int | None = None,
    ref: int | None = None,
) -> dict[str, Any]:
    """Click an element by CSS selector or @ref from the latest browser_snapshot."""
    payload: dict[str, Any] = {**_tab_kwargs(tab_id)}
    if ref is not None:
        payload["ref"] = ref
    if selector:
        payload["selector"] = selector
    return await _forward_to_bridge("browser_click", payload)


@mcp.tool()
async def browser_fill(
    selector: str = "",
    value: str = "",
    tab_id: int | None = None,
    ref: int | None = None,
) -> dict[str, Any]:
    """Type into an input by CSS selector or @ref from the latest browser_snapshot."""
    payload: dict[str, Any] = {"value": value, **_tab_kwargs(tab_id)}
    if ref is not None:
        payload["ref"] = ref
    if selector:
        payload["selector"] = selector
    return await _forward_to_bridge("browser_fill", payload)


@mcp.tool()
async def browser_get_elements(
    selector: str,
    attributes: list[str] | None = None,
    tab_id: int | None = None,
) -> dict[str, Any]:
    """Return elements matching a CSS selector (searches all frames)."""
    args: dict[str, Any] = {"selector": selector, **_tab_kwargs(tab_id)}
    if attributes is not None:
        args["attributes"] = attributes
    return await _forward_to_bridge("browser_get_elements", args)


@mcp.tool()
async def browser_evaluate(expression: str, tab_id: int | None = None) -> dict[str, Any]:
    """Evaluate a JavaScript expression in the page context and return the result."""
    return await _forward_to_bridge(
        "browser_evaluate",
        {"expression": expression, **_tab_kwargs(tab_id)},
    )


@mcp.tool()
async def browser_snapshot(tab_id: int | None = None) -> dict[str, Any]:
    """Return a compact accessibility-style snapshot (includes iframe content)."""
    return await _forward_to_bridge("browser_snapshot", _tab_kwargs(tab_id))


@mcp.tool()
async def browser_get_network(tab_id: int | None = None) -> dict[str, Any]:
    """Return recent network activity for a tab from the Resource Timing API."""
    return await _forward_to_bridge("browser_get_network", _tab_kwargs(tab_id))


@mcp.tool()
async def browser_get_console(max: int = 100, tab_id: int | None = None) -> dict[str, Any]:
    """Return captured console output for a tab."""
    return await _forward_to_bridge("browser_get_console", {"max": max, **_tab_kwargs(tab_id)})


# ─────────────────────────────────────────────
# v2 browser tools
# ─────────────────────────────────────────────

@mcp.tool()
async def browser_highlight(
    selectors: list[str],
    labels: list[str] | None = None,
    tab_id: int | None = None,
) -> dict[str, Any]:
    """Visually highlight one or more elements on the page with coloured overlays.

    selectors: CSS selectors to highlight.
    labels: optional display label for each overlay (same length as selectors).
    """
    args: dict[str, Any] = {"selectors": selectors, **_tab_kwargs(tab_id)}
    if labels is not None:
        args["labels"] = labels
    return await _forward_to_bridge("browser_highlight", args)


@mcp.tool()
async def browser_wait_for_selector(
    selector: str,
    timeout_ms: int = 5000,
    tab_id: int | None = None,
) -> dict[str, Any]:
    """Wait until an element matching selector appears in the DOM (or timeout)."""
    return await _forward_to_bridge(
        "browser_wait_for_selector",
        {"selector": selector, "timeout_ms": timeout_ms, **_tab_kwargs(tab_id)},
        timeout=timeout_ms / 1000 + 5,
    )


@mcp.tool()
async def browser_wait_for_navigation(
    timeout_ms: int = 10000,
    tab_id: int | None = None,
) -> dict[str, Any]:
    """Wait until a tab finishes navigating (document.readyState == 'complete')."""
    return await _forward_to_bridge(
        "browser_wait_for_navigation",
        {"timeout_ms": timeout_ms, **_tab_kwargs(tab_id)},
        timeout=timeout_ms / 1000 + 5,
    )


@mcp.tool()
async def browser_assert_text(
    text: str,
    selector: str | None = None,
    tab_id: int | None = None,
) -> dict[str, Any]:
    """Assert that text is present in the page (or within selector if provided).

    Returns {present: true} when the text is found, {present: false} when not.
    """
    args: dict[str, Any] = {"text": text, **_tab_kwargs(tab_id)}
    if selector is not None:
        args["selector"] = selector
    return await _forward_to_bridge("browser_assert_text", args)


@mcp.tool()
async def browser_scroll_to(selector: str, tab_id: int | None = None) -> dict[str, Any]:
    """Scroll the element matching selector into view."""
    return await _forward_to_bridge("browser_scroll_to", {"selector": selector, **_tab_kwargs(tab_id)})


@mcp.tool()
async def browser_select_option(
    selector: str,
    value: str,
    tab_id: int | None = None,
) -> dict[str, Any]:
    """Select an option: native <select> by value, or ARIA/Cloudscape dropdown by label text."""
    return await _forward_to_bridge(
        "browser_select_option",
        {"selector": selector, "value": value, **_tab_kwargs(tab_id)},
    )


@mcp.tool()
async def browser_hover(selector: str, tab_id: int | None = None) -> dict[str, Any]:
    """Hover the mouse over an element to reveal tooltips or sub-menus."""
    return await _forward_to_bridge("browser_hover", {"selector": selector, **_tab_kwargs(tab_id)})


@mcp.tool()
async def browser_key_press(
    key: str,
    selector: str | None = None,
    tab_id: int | None = None,
) -> dict[str, Any]:
    """Dispatch a keyboard event (e.g. 'Enter', 'Escape', 'Tab', 'ArrowDown').

    If selector is provided the key is dispatched on that element; otherwise
    it is dispatched on document.activeElement.
    """
    args: dict[str, Any] = {"key": key, **_tab_kwargs(tab_id)}
    if selector is not None:
        args["selector"] = selector
    return await _forward_to_bridge("browser_key_press", args)


@mcp.tool()
async def browser_upload_file(
    selector: str,
    source: str,
    tab_id: int | None = None,
) -> dict[str, Any]:
    """Inject a local file or URL into a file input (type=file) via MAIN-world DataTransfer.

    source = local filesystem path OR an http(s):// URL.
    Use for resume/CV uploads (e.g. Workday) that normal fill/click cannot set.
    The file is fetched/read on the bridge side, base64-encoded, and injected
    into the page's MAIN world via DataTransfer so React/Angular file inputs
    register the change correctly.
    """
    import urllib.parse

    parsed = urllib.parse.urlparse(source)
    if parsed.scheme in ("http", "https"):
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(source, follow_redirects=True)
                resp.raise_for_status()
                file_bytes = resp.content
        except Exception as exc:
            return {"ok": False, "error": f"Failed to fetch {source!r}: {exc}"}
        filename = parsed.path.split("/")[-1] or "upload"
    else:
        file_path = Path(source)
        if not file_path.exists():
            return {"ok": False, "error": f"File not found: {source!r}"}
        file_bytes = file_path.read_bytes()
        filename = file_path.name

    mime, _ = mimetypes.guess_type(filename)
    if mime is None:
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        mime = "application/pdf" if ext == "pdf" else "application/octet-stream"

    b64 = base64.b64encode(file_bytes).decode("ascii")
    return await _forward_to_bridge(
        "browser_upload_file",
        {"selector": selector, "base64": b64, "filename": filename, "mime": mime, **_tab_kwargs(tab_id)},
    )


@mcp.tool()
async def linkedin_scrape_feed(max_posts: int = 20, tab_id: int | None = None) -> dict[str, Any]:
    """Scrape visible LinkedIn feed cards (author, text, urn, postUrl) via DevScope content script."""
    return await _forward_to_bridge(
        "linkedin_scrape_feed",
        {"max_posts": max_posts, **_tab_kwargs(tab_id)},
    )


@mcp.tool()
async def linkedin_fill_composer(
    text: str,
    auto_send: bool = False,
    allow_send: bool = False,
    tab_id: int | None = None,
) -> dict[str, Any]:
    """Fill LinkedIn post composer. Send only when allow_send=true (guarded auto whitelist)."""
    return await _forward_to_bridge(
        "linkedin_fill_composer",
        {"text": text, "auto_send": auto_send, "allow_send": allow_send, **_tab_kwargs(tab_id)},
    )


@mcp.tool()
async def linkedin_fill_comment(
    text: str,
    post_selector: str | None = None,
    allow_send: bool = False,
    tab_id: int | None = None,
) -> dict[str, Any]:
    """Fill a LinkedIn comment draft; posting requires allow_send=true + approval."""
    payload: dict[str, Any] = {"text": text, "allow_send": allow_send, **_tab_kwargs(tab_id)}
    if post_selector:
        payload["post_selector"] = post_selector
    return await _forward_to_bridge("linkedin_fill_comment", payload)


@mcp.tool()
async def linkedin_scrape_people_search(
    max_profiles: int = 25,
    max_pages: int = 1,
    tab_id: int | None = None,
) -> dict[str, Any]:
    """Deep-scrape LinkedIn people search results (page JSON → API cache → DOM)."""
    return await _forward_to_bridge(
        "linkedin_scrape_people_search",
        {"max_profiles": max_profiles, "max_pages": max_pages, **_tab_kwargs(tab_id)},
        timeout=120.0,
    )


@mcp.tool()
async def linkedin_read_search_state(tab_id: int | None = None) -> dict[str, Any]:
    """Read active LinkedIn people search filters and scrape metadata."""
    return await _forward_to_bridge(
        "linkedin_read_search_state",
        {**_tab_kwargs(tab_id)},
    )


@mcp.tool()
async def linkedin_scrape_profile(
    full: bool = True,
    initial_wait: int = 2500,
    tab_id: int | None = None,
) -> dict[str, Any]:
    """Scrape the current LinkedIn profile page in the bound/active tab."""
    return await _forward_to_bridge(
        "linkedin_scrape_profile",
        {"full": full, "initial_wait": initial_wait, **_tab_kwargs(tab_id)},
        timeout=90.0,
    )


# ─────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s %(message)s",
    )
    mcp.run(transport="stdio")
