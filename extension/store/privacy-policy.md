# DevScope — Privacy Policy

_Last updated: 2026-05-29_

DevScope is a developer tool that runs your own local AI coding agent (the `claude` or Cursor CLI) inside a Chrome side panel. Privacy is structural, not a promise: the extension is built so that your data never leaves your machine.

## The short version

- DevScope talks to **one endpoint only**: a small bridge running locally on your own computer at `http://127.0.0.1:7878` (and the loopback WebSocket `ws://127.0.0.1:7878`).
- There are **no DevScope servers**. We do not operate any backend, and the extension does not send your data to us or to any third party.
- There is **no analytics, tracking, or telemetry** of any kind.
- All of your data — chat history, your bridge token, and your project paths — is stored **locally** in your browser via `chrome.storage.local` (and your theme preference in `localStorage`). It stays on your device.

## What data the extension handles, and where it lives

- **Chat history** — Your messages and the agent's replies are saved in `chrome.storage.local` (capped to the most recent messages per session) so conversations persist across side-panel opens. Stored on your machine only.
- **Bridge token** — The authentication token printed by your local bridge is stored in `chrome.storage.local` and sent only to the local bridge (as an `Authorization: Bearer` header over HTTP, or in the loopback WebSocket handshake). It is never transmitted anywhere else.
- **Project paths** — Working-directory paths you configure for sessions are stored in `chrome.storage.local`. They are sent only to the local bridge so the agent runs in the right project.
- **Theme preference** — Stored in `localStorage` so the side panel can render in the correct theme without a flash.

## How DevScope interacts with web pages

When you ask the agent to act on the page you're viewing, DevScope uses Chrome's scripting APIs to perform that action on the **active tab only** (read elements, click, fill fields, navigate, or capture a screenshot of the visible tab). This happens locally in your browser, and the results are passed to your **local** agent through the local bridge. DevScope does not transmit page contents, screenshots, or URLs to any remote server — there is no remote server to send them to.

DevScope does not act on a page unless you ask the agent to. Pages such as `chrome://`, `chrome-extension://`, and other restricted URLs are never scripted.

## The local bridge

The bridge is software you install and run yourself (`pipx install devscope-bridge`, then `devscope-bridge`). It binds exclusively to the loopback interface (`127.0.0.1`) and refuses to bind to any non-loopback host. The bridge launches and streams output from your own locally installed `claude` or Cursor CLI, using your own model credentials. Whatever those CLIs do with your data is governed by their own providers' terms and is outside DevScope's control; DevScope itself adds no additional data collection.

## Third parties

None. DevScope integrates with no third-party services, SDKs, or analytics providers.

## Data retention and deletion

Because all data lives in your browser's local storage on your device, you remain in full control. You can clear it at any time by removing the extension, or by clearing the extension's storage from Chrome. Uninstalling DevScope removes its `chrome.storage.local` data.

## Affiliation

DevScope is an independent project and is not affiliated with, sponsored by, or endorsed by Anthropic (Claude) or Anysphere (Cursor).

## Contact

For privacy questions, contact the maintainer through the extension's Chrome Web Store support channel.
