---
name: devscope-browser
description: Use DevScope browser-control MCP tools to drive the user's Chrome via the extension — list tabs across profiles, navigate, snapshot, click, fill, screenshot. Use when the user asks to open a page, interact with the current tab, scrape what they see, test a web app, or any browser automation from DevScope chat.
---

# DevScope Browser Control

Claude sessions in DevScope talk to Chrome through the **browser-control** MCP server → local bridge → Chrome extension.

## Prerequisites (check before failing silently)

1. **DevScope side panel open** in Chrome (bridge WS connected).
2. **Tab bound** for this session (globe pill in composer) — or use `browser_list_tabs` and `browser_focus_tab`.
3. **`DEVSCOPE_SESSION`** is set by the bridge — tools route to the correct extension profile.

If tools return `503 Browser client not connected` → ask the user to open DevScope and reconnect.

## Tool selection

| Goal | Tool |
|------|------|
| See all tabs (all Chrome profiles) | `browser_list_tabs` |
| Switch tab | `browser_focus_tab` |
| Open URL | `browser_navigate` |
| Understand page structure | `browser_snapshot` (preferred) or `browser_get_elements` |
| Screenshot | `browser_screenshot` |
| Click / fill / select | `browser_click`, `browser_fill`, `browser_select_option` |
| Run JS on page | `browser_evaluate` |
| Wait for UI | `browser_wait_for_selector`, `browser_wait_for_navigation` |
| Debug | `browser_get_console`, `browser_get_network` |

## Workflow

1. **`browser_list_tabs`** — find the target tab; note `profile_id` if multiple profiles.
2. **`browser_focus_tab`** — bind/focus before actions if needed.
3. **`browser_snapshot`** — read structure before click/fill (LinkedIn, SPAs, shadow DOM).
4. Act with **`browser_click`** / **`browser_fill`** using selectors from snapshot.
5. Re-snapshot after navigation or major DOM changes.

## Cross-profile

`browser_list_tabs` returns tabs from **every Chrome profile** with DevScope installed. Actions on a `tab_id` route to the owning profile automatically.

## Restrictions

- **inspect mode** allows read-only browser tools only (no navigate/click).
- Restricted URLs (`chrome://`, extension pages) cannot be scripted.
- WhatsApp Store reads use **whatsapp-control** MCP, not generic DOM scraping.

## Errors

| Error | Fix |
|-------|-----|
| `Browser client not connected` | Open DevScope panel |
| `Tab not found` | Re-list tabs; user may have closed it |
| `No active tab` | Bind tab via globe pill or focus one |
