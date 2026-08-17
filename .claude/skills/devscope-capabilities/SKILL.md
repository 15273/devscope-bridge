---
name: devscope-capabilities
description: Index of DevScope-integrated capabilities for Claude in the side panel — browser-control, whatsapp-control, gmail-control, calendar-control, task-control MCP servers and when to use each.
---

# DevScope Capabilities

DevScope sessions run **Claude Code** with project `.mcp.json` MCP servers.

## MCP servers

| Server | When to use | Skill |
|--------|-------------|-------|
| **browser-control** | Web pages, clicks, snapshots, tabs | `devscope-browser` |
| **whatsapp-control** | Read WhatsApp chats/messages | `comms-cockpit` |
| **gmail-control** | Search/read email | `comms-cockpit` |
| **calendar-control** | Events, free slots, scheduling | this file |
| **task-control** | Orchestrator task board | this file |
| **devscope-control** | Notion / Cursor plugins, codebase scout | this file |
| **meta-ads-control** | Facebook Ads Manager | `meta-ads-cockpit` |

## Browser

See **devscope-browser**. Requires DevScope extension connected + a bound tab.

## WhatsApp / Gmail

See **comms-cockpit**. WhatsApp needs web.whatsapp.com open and bound. Gmail needs `~/.dev-bridge/gmail_token.json`.

## Calendar

- Tools: `cal_list_events`, `cal_get_event`, `cal_find_free_slots`
- Write: `cal_validate_event_draft` then `cal_create_event` only after explicit user confirmation
- Token: `~/.dev-bridge/calendar_token.json`
- Setup: `python -m devscope_bridge.calendar.authorize_calendar`

## Tasks

Use for orchestrator workflows. Always go through MCP, not the SQLite file.

## devscope_invoke (`devscope-control`)

- `devscope_invoke(capability, task, wait=True)`
- `devscope_capabilities()` — list capabilities with live `available` + setup hints

Use for Notion / Cursor plugins. Do **not** use this for browser, WhatsApp, Gmail, Calendar, or tasks — those have dedicated MCP tools.

## Setup checklist

1. Bridge running: `devscope-bridge`
2. Token pasted in DevScope Settings
3. Side panel open + session connected
4. Tab bound (globe) for browser/WhatsApp
5. Optional OAuth for Gmail/Calendar
6. Optional: `python -m devscope_bridge.setup_mcp`
