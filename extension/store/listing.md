# Chrome Web Store Listing — DevScope

## Extension name

DevScope — Local AI agent in your side panel

## Short description (≤132 chars)

Chat with your local Claude or Cursor CLI from a Chrome side panel — and let it act on the page you're looking at. Local-only.

<!-- 128 chars -->

## Full description

DevScope puts your own local coding agent — the `claude` or Cursor CLI already running on your machine — into a Chrome side panel, right next to the page you're working on.

Ask a question, paste an error, or describe a change, and the agent answers with streaming responses, syntax-highlighted code blocks, and full Markdown. Because it's the same CLI you run in your terminal, it works in your real projects, with your real files and your own model access — nothing is re-implemented in the cloud.

DevScope can also act on the live tab. Give the agent a task and it can read the current page, inspect elements, fill fields, click, navigate, and capture a screenshot of what you're seeing — so "reproduce this bug" or "fill this form like X" becomes a single instruction instead of a manual chore.

Everything stays on your computer. DevScope talks to one thing only: a small bridge you run locally at 127.0.0.1:7878. There are no DevScope servers, no analytics, and no telemetry. Your chat history, your bridge token, and your project paths live in your browser's local storage on your machine — not ours.

Built for developers who already live in the terminal but want their agent one keystroke away while they browse docs, dashboards, and the app they're building.

How it works:
1. Install the local bridge once: `pipx install devscope-bridge`
2. Start it in a terminal: `devscope-bridge`
3. Paste the printed token into DevScope Settings, and you're connected.

DevScope is an independent project and is not affiliated with or endorsed by Anthropic or Anysphere (Cursor).

## Feature bullets

- Chat with your local `claude` or Cursor CLI from a Chrome side panel — streaming replies, Markdown, and syntax-highlighted code blocks.
- Let the agent act on the page you're viewing: read content, inspect and click elements, fill forms, navigate, and screenshot the live tab.
- Multiple named sessions with per-project working directories, so each conversation runs in the right codebase.
- Local-only by design — connects solely to a bridge at 127.0.0.1:7878; no cloud servers, no analytics, no telemetry.
- Polished light and dark themes (the warm "Graphite" amber design language) with a connection indicator that shows bridge status at a glance.

## Single permission-justification paragraph

DevScope requests only the permissions it needs to run a local agent in the side panel and let that agent act on the current tab. `sidePanel` opens the DevScope chat UI in Chrome's side panel. `storage` keeps your settings, chat history, project paths, and bridge token in `chrome.storage.local` on your own machine. `offscreen` hosts a background document that maintains the long-lived loopback WebSocket connection to the local bridge for streaming agent output. `tabs` lets the agent list open tabs and read the active tab's URL/title so it knows what you're looking at. `scripting` plus `activeTab` let the agent perform the page actions you request — read elements, click, fill fields, and capture a screenshot of the current tab. The `host_permissions` for `http://127.0.0.1:7878/*` and `ws://127.0.0.1:7878/*` are the loopback addresses of the local bridge DevScope talks to — these never leave your computer. `<all_urls>` is required because page actions can apply to whatever site you're currently on; DevScope only touches a page when you ask the agent to act, and it never sends page contents to any remote server.
