"""capabilities.py — DevScope MCP + integration readiness for the extension UI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from devscope_bridge import browser_relay

_GMAIL_TOKEN = Path.home() / ".dev-bridge" / "gmail_token.json"
_CALENDAR_TOKEN = Path.home() / ".dev-bridge" / "calendar_token.json"
_META_ADS_TOKEN = Path.home() / ".dev-bridge" / "meta_ads_token.json"

DEVSCOPE_MCP_SERVERS: dict[str, dict[str, Any]] = {
    "browser-control": {
        "label": "Browser",
        "description": "Navigate, click, snapshot, and list tabs via the DevScope Chrome extension.",
        "tools_hint": "browser_list_tabs, browser_snapshot, browser_click, …",
        "skill": "devscope-browser",
    },
    "whatsapp-control": {
        "label": "WhatsApp",
        "description": "Read chats and messages from web.whatsapp.com (bound tab + Store grab).",
        "tools_hint": "wa_list_chats, wa_get_messages, wa_search",
        "skill": "comms-cockpit",
    },
    "gmail-control": {
        "label": "Gmail",
        "description": "Search and read Gmail threads via OAuth (Gmail API).",
        "tools_hint": "gm_search_threads, gm_get_thread, gm_list_labels",
        "skill": "comms-cockpit",
    },
    "calendar-control": {
        "label": "Calendar",
        "description": "List events, find free slots, create events (with user confirmation).",
        "tools_hint": "cal_list_events, cal_find_free_slots, cal_create_event",
        "skill": "devscope-capabilities",
    },
    "task-control": {
        "label": "Task board",
        "description": "Orchestrator task board — create, claim, and complete agent tasks.",
        "tools_hint": "task_list, task_create, task_claim, …",
        "skill": "devscope-capabilities",
    },
    "meta-ads-control": {
        "label": "Meta Ads",
        "description": "Facebook Ads Manager — campaigns, insights, alerts (Marketing API).",
        "tools_hint": "meta_list_campaigns, meta_get_insights, meta_update_campaign_status",
        "skill": "meta-ads-cockpit",
    },
    "meta-ads-official": {
        "label": "Meta Ads (official MCP)",
        "description": "Meta hosted MCP at mcp.facebook.com/ads (OAuth via Claude).",
        "tools_hint": "Meta official reporting / catalog tools",
        "skill": "meta-ads-cockpit",
    },
}

DEVSCOPE_SKILLS: list[dict[str, str]] = [
    {"id": "devscope-capabilities", "label": "DevScope capabilities", "path": ".claude/skills/devscope-capabilities"},
    {"id": "devscope-browser", "label": "Browser control", "path": ".claude/skills/devscope-browser"},
    {"id": "comms-cockpit", "label": "WhatsApp + Gmail", "path": ".claude/skills/comms-cockpit"},
    {"id": "meta-ads-cockpit", "label": "Meta Ads Manager", "path": ".claude/skills/meta-ads-cockpit"},
]


def _browser_status() -> dict[str, Any]:
    summary = browser_relay.connection_summary()
    sessions = summary["connected_sessions"]
    return {
        "ready": sessions > 0,
        **summary,
        "hint": (
            "Open DevScope side panel in Chrome and bind a tab (globe pill)."
            if sessions == 0
            else None
        ),
    }


def _token_ready(path: Path, setup_cmd: str) -> dict[str, Any]:
    ok = path.is_file() and path.stat().st_size > 2
    return {
        "ready": ok,
        "token_path": str(path),
        "setup_command": setup_cmd if not ok else None,
    }


def build_capabilities() -> dict[str, Any]:
    browser = _browser_status()
    gmail = _token_ready(
        _GMAIL_TOKEN,
        "GOOGLE_CLIENT_ID=... GOOGLE_CLIENT_SECRET=... python -m devscope_bridge.gmail.authorize_gmail",
    )
    calendar = _token_ready(
        _CALENDAR_TOKEN,
        "GOOGLE_CLIENT_ID=... GOOGLE_CLIENT_SECRET=... python -m devscope_bridge.calendar.authorize_calendar",
    )
    meta_ads = _token_ready(
        _META_ADS_TOKEN,
        "FACEBOOK_APP_ID=... FACEBOOK_APP_SECRET=... python -m devscope_bridge.meta_ads.authorize_meta_ads",
    )

    servers: list[dict[str, Any]] = []
    for sid, meta in DEVSCOPE_MCP_SERVERS.items():
        entry: dict[str, Any] = {"id": sid, **meta}
        if sid == "browser-control":
            entry["status"] = browser
            entry["ready"] = browser["ready"]
        elif sid == "gmail-control":
            entry["status"] = gmail
            entry["ready"] = gmail["ready"]
        elif sid == "calendar-control":
            entry["status"] = calendar
            entry["ready"] = calendar["ready"]
        elif sid == "meta-ads-control":
            entry["status"] = meta_ads
            entry["ready"] = meta_ads["ready"]
        elif sid == "meta-ads-official":
            entry["status"] = {
                "ready": True,
                "requires": "claude mcp add --transport http meta-ads-official https://mcp.facebook.com/ads",
            }
            entry["ready"] = True
        elif sid == "whatsapp-control":
            entry["status"] = {
                "ready": browser["ready"],
                "requires": "web.whatsapp.com tab open + bound to this session",
                "hint": "Open WhatsApp Web, bind the tab in DevScope, then use wa_list_chats.",
            }
            entry["ready"] = browser["ready"]
        else:
            entry["status"] = {"ready": True}
            entry["ready"] = True
        servers.append(entry)

    return {
        "mcp_servers": servers,
        "skills": DEVSCOPE_SKILLS,
        "setup": {
            "mcp_config": ".mcp.json",
            "claude_setup": "python -m devscope_bridge.setup_mcp",
            "note": "Claude sessions spawned from DevScope load MCP from the session cwd .mcp.json.",
        },
    }
