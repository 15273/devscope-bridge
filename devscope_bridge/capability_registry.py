"""
capability_registry.py — single source of truth for what DevScope can do.

Additive layer over existing mechanisms: each capability points at the ordered
backends that already serve it (cursor-agent subprocess, claude --print, or a
direct MCP server the Claude session loads itself).  Nothing here replaces the
slash commands or the MCP servers — invocation lives in capability_router.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from devscope_bridge.background_cursor_task import _mcp_list_status
from devscope_bridge.capabilities import _browser_status, _token_ready
from devscope_bridge.capabilities import _CALENDAR_TOKEN, _GMAIL_TOKEN
from devscope_bridge.session_manager_cursor import _resolve_cursor_bin

_MCP_STATUS_TTL_S = 60.0
_mcp_status_cache: tuple[float, dict[str, str]] | None = None


@dataclass(frozen=True)
class Capability:
    id: str
    label: str
    backends: tuple[str, ...]          # ordered fallback chain
    requires: tuple[str, ...]          # requirement probe ids (see _probe)
    consumer_visible: bool = True
    description: str = ""
    mcp_hint: str = ""                 # direct-MCP tool names, when backends include direct_mcp
    setup_hint: str = ""               # shown when a requirement is missing


CAPABILITIES: dict[str, Capability] = {
    "browser": Capability(
        id="browser", label="Browser", backends=("direct_mcp",),
        requires=("extension_connected",),
        description="Navigate, click, snapshot, and read tabs via the DevScope extension.",
        mcp_hint="browser_list_tabs, browser_snapshot, browser_click, …",
        setup_hint="Open the DevScope side panel in Chrome and bind a tab.",
    ),
    "whatsapp": Capability(
        id="whatsapp", label="WhatsApp", backends=("direct_mcp",),
        requires=("extension_connected",),
        description="Read chats and messages from the bound web.whatsapp.com tab.",
        mcp_hint="wa_list_chats, wa_get_messages, wa_search",
        setup_hint="Open WhatsApp Web and bind the tab in DevScope.",
    ),
    "gmail": Capability(
        id="gmail", label="Gmail", backends=("direct_mcp",),
        requires=("gmail_token",),
        description="Search and read Gmail threads via OAuth.",
        mcp_hint="gm_search_threads, gm_get_thread, gm_list_labels",
        setup_hint=".venv/bin/python -m devscope_bridge.gmail.authorize_gmail",
    ),
    "calendar": Capability(
        id="calendar", label="Calendar", backends=("direct_mcp",),
        requires=("calendar_token",),
        description="List events, find free slots, create events (with confirmation).",
        mcp_hint="cal_list_events, cal_find_free_slots, cal_create_event",
        setup_hint=".venv/bin/python -m devscope_bridge.calendar.authorize_calendar",
    ),
    "notion": Capability(
        id="notion", label="Notion", backends=("cursor_agent",),
        requires=("cursor_agent_bin", "cursor_plugin:notion"),
        description="Read Notion tasks and pages via the Cursor Notion plugin.",
        setup_hint="Connect Notion in Cursor IDE → Settings → MCP / Plugins.",
    ),
    "cursor_plugins": Capability(
        id="cursor_plugins", label="Cursor plugins", backends=("cursor_agent",),
        requires=("cursor_agent_bin",), consumer_visible=False,
        description="Run any task with Cursor's MCP plugins (generic /cursor-task path).",
        setup_hint="Install cursor-agent and ensure it is on PATH.",
    ),
    "codebase_scout": Capability(
        id="codebase_scout", label="Codebase scout", backends=("cursor_agent_ctx",),
        requires=("cursor_agent_bin",), consumer_visible=False,
        description="Read-only repo exploration (files, symbols, data flow).",
        setup_hint="Install cursor-agent and ensure it is on PATH.",
    ),
    "parallel_ask": Capability(
        id="parallel_ask", label="Side question", backends=("claude_print",),
        requires=(), consumer_visible=False,
        description="Quick parallel question answered by a separate claude --print turn.",
    ),
}


async def cursor_mcp_status() -> dict[str, str]:
    """`cursor-agent mcp list` output, TTL-cached (the probe shells a subprocess)."""
    global _mcp_status_cache
    now = time.monotonic()
    if _mcp_status_cache is not None and now - _mcp_status_cache[0] < _MCP_STATUS_TTL_S:
        return _mcp_status_cache[1]
    status = await asyncio.to_thread(_mcp_list_status)
    _mcp_status_cache = (now, status)
    return status


def _plugin_ready(status: dict[str, str], plugin: str) -> bool:
    needle = plugin.lower()
    return any(
        needle in name.lower() and state.lower().startswith("ready")
        for name, state in status.items()
    )


async def _probe(requirement: str) -> bool:
    if requirement == "extension_connected":
        return bool(_browser_status()["ready"])
    if requirement == "gmail_token":
        return bool(_token_ready(_GMAIL_TOKEN, "")["ready"])
    if requirement == "calendar_token":
        return bool(_token_ready(_CALENDAR_TOKEN, "")["ready"])
    if requirement == "cursor_agent_bin":
        return bool(_resolve_cursor_bin())
    if requirement.startswith("cursor_plugin:"):
        plugin = requirement.split(":", 1)[1]
        return _plugin_ready(await cursor_mcp_status(), plugin)
    return False


async def check_requires(cap: Capability) -> dict[str, bool]:
    """Map each requirement id of ``cap`` to whether it is currently satisfied."""
    results = await asyncio.gather(*(_probe(r) for r in cap.requires))
    return dict(zip(cap.requires, results))


def plugin_capability(plugin: str) -> Capability:
    """Mint a capability for one Cursor plugin/MCP (generic — any plugin works)."""
    return Capability(
        id=f"plugin:{plugin}",
        label=plugin.capitalize(),
        backends=("cursor_agent",),
        requires=("cursor_agent_bin", f"cursor_plugin:{plugin}"),
        description=f"Run tasks with the Cursor '{plugin}' plugin/MCP.",
        setup_hint=f"Connect '{plugin}' in Cursor IDE → Settings → MCP / Plugins.",
    )


async def dynamic_plugin_capabilities() -> list[Capability]:
    """One capability per ready Cursor plugin (from the cached `cursor-agent mcp list`).

    DevScope's own MCP servers (also registered in .cursor/mcp.json) are skipped —
    Claude reaches those directly; routing them through cursor-agent is circular.
    """
    from devscope_bridge.capabilities import DEVSCOPE_MCP_SERVERS

    status = await cursor_mcp_status()
    plugins = []
    for name, state in status.items():
        if not state.lower().startswith("ready"):
            continue
        if name in DEVSCOPE_MCP_SERVERS:
            continue
        if "notion" in name.lower():
            continue  # the static friendly 'notion' entry already covers it
        plugins.append(plugin_capability(name))
    return plugins


def get_capability(capability_id: str) -> Capability | None:
    if capability_id.startswith("plugin:"):
        return plugin_capability(capability_id.split(":", 1)[1])
    return CAPABILITIES.get(capability_id)


def _serialize(cap: Capability, requires: dict[str, bool]) -> dict:
    available = all(requires.values())
    return {
        "id": cap.id,
        "label": cap.label,
        "description": cap.description,
        "backends": list(cap.backends),
        "consumer_visible": cap.consumer_visible,
        "available": available,
        "active_backend": cap.backends[0] if available else None,
        "missing": [r for r, ok in requires.items() if not ok],
        "mcp_hint": cap.mcp_hint or None,
        "setup_hint": cap.setup_hint if not available else None,
    }


async def list_capabilities() -> list[dict]:
    """Serialized registry entries (static + live Cursor plugins), for GET /capabilities."""
    caps = list(CAPABILITIES.values()) + await dynamic_plugin_capabilities()
    checks = await asyncio.gather(*(check_requires(c) for c in caps))
    return [_serialize(cap, req) for cap, req in zip(caps, checks)]
