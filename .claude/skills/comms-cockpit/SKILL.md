---
name: comms-cockpit
description: Read WhatsApp chats and Gmail threads from DevScope — use whatsapp-control and gmail-control MCP tools when the user asks about messages, email, inbox, WhatsApp groups, or the comms cockpit.
---

# Comms Cockpit — WhatsApp + Email

DevScope can read WhatsApp and Gmail through engines in `devscope_bridge/`, each exposed twice: as a FastAPI route (side panel cockpit) and as a stdio MCP server (the agent).

WhatsApp is **read-only**; there is no `wa.send` yet.

## WhatsApp — live-tab Store grab

There is **no official personal WhatsApp API**. DevScope reads the live `web.whatsapp.com` tab by injecting a script into the page's **MAIN world** that grabs WhatsApp's internal webpack `Store`. DOM scraping is a last-resort fallback — WhatsApp's classes are hashed.

### Flow

```
UI / agent → /wa/* route OR wa_* MCP tool
  → whatsapp_engine.py
  → browser_relay.post_action → WS → extension
  → browser_tools.ts case 'browser_wa_store' → wa_store_runner.ts
  → chrome.scripting.executeScript({ world: 'MAIN' }) runs whatsapp_store_inject.js
```

### Key files

- `devscope_bridge/whatsapp/whatsapp_store_inject.js` — canonical MAIN-world script
- `extension/src/background/wa_store_runner.ts` — injects the script (`world:'MAIN'`). Keep in sync with the JS file.
- `devscope_bridge/whatsapp/whatsapp_engine.py`
- `devscope_bridge/whatsapp/whatsapp_store_map.json` — webpack module-id hints + DOM fallbacks

### MCP / routes

- `GET /wa/chats`, `GET /wa/messages`, `GET /wa/search`
- Tools: `wa_list_chats`, `wa_get_messages`, `wa_search`
- `store_unavailable` → ask the user to refresh the WhatsApp Web tab

## Gmail — Gmail API

Email uses the **Gmail API** (OAuth token on disk), not Gmail's obfuscated DOM.

```bash
GOOGLE_CLIENT_ID=... GOOGLE_CLIENT_SECRET=... python -m devscope_bridge.gmail.authorize_gmail
```

Writes `~/.dev-bridge/gmail_token.json` (mode 0600).

- Routes: `GET /gm/threads`, `GET /gm/thread`, `GET /gm/labels`
- Tools: `gm_search_threads`, `gm_get_thread`, `gm_list_labels`

## Safety

Any future send (`wa.send`, `gm.send`) must be draft-first with an explicit confirm dialog. Destructive actions are never autonomous.
