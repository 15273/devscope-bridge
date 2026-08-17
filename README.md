# DevScope

Local side-panel for **Claude Code** (and optionally Cursor) inside Chrome.

The Chrome extension talks to a loopback-only Python bridge on `127.0.0.1:7878`.
The bridge launches your already-installed `claude` / `cursor-agent` CLIs. Nothing
is sent to a DevScope cloud — there isn’t one.

This directory is a **standalone snapshot**, not coupled to any other product.

---

## What you need

| Thing | Why |
|---|---|
| macOS or Linux, Python **3.11+** | Runs the bridge |
| [Claude CLI](https://claude.ai/download) logged in (`claude login`) | The agent |
| Chrome | Hosts the side panel |
| Node.js 18+ | Builds the extension once |
| Cursor CLI (optional) | Only if you create Cursor-agent sessions |

Verify Claude is on PATH:

```bash
which claude && claude --version
```

---

## 1. Install the bridge

From this folder:

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e .
```

That puts `devscope-bridge` on PATH *inside the venv*.

### Start it once (foreground)

```bash
devscope-bridge
# or: python -m devscope_bridge.main
```

It prints:

```
Dev Bridge started. Token: <hex>
```

and writes the same value to `~/.dev-bridge/token` (chmod 0600). The token is
**reused** across restarts — you only paste it into the extension once.

Keep this terminal open, or install the macOS service in step 4.

Check:

```bash
curl http://127.0.0.1:7878/health
# {"ok":true,"version":"0.1","uptime_s":…}
```

### Environment (optional)

| Variable | Default | Purpose |
|---|---|---|
| `BRIDGE_HOST` | `127.0.0.1` | Bind address. **Loopback only** — other hosts are rejected. |
| `BRIDGE_PORT` | `7878` | TCP port |
| `BRIDGE_EXTENSION_ID` | placeholder | Chrome origin added to CORS, e.g. `chrome-extension://abcdef…` |
| `ORCHESTRATOR_MAX_WORKERS` | `3` | Max concurrent Claude worker tasks |
| `CURSOR_BIN` | macOS Cursor.app path | Cursor CLI binary |

Copy `.env.example` → `devscope_bridge/.env.local` if you prefer a file (gitignored).

**Do not** run the bridge with `uvicorn --workers 2+`. PTY terminals, WebSockets,
and the orchestrator live in one process. `workers=1` is required.

---

## 2. Build and load the Chrome extension

```bash
cd extension
npm install
npm run build
```

In Chrome:

1. `chrome://extensions`
2. Enable **Developer mode** (top right)
3. **Load unpacked** → select **`extension/dist/`** (the built folder, not `src/`)
4. Copy the **ID** shown on the DevScope card (32 characters)

Pin the icon if you want. Click it to open the side panel.

---

## 3. Connect extension ↔ bridge

Restart the bridge so CORS trusts this install:

```bash
export BRIDGE_EXTENSION_ID="chrome-extension://PASTE_THE_ID_HERE"
devscope-bridge
```

In the side panel: **gear (Settings)** → paste:

```bash
cat ~/.dev-bridge/token
```

into **Bridge token** → Save / Test connection.

The connection pip in the header turns **green** when the WebSocket is live.

First chat: **New chat** → pick a project folder (your code) → send a message.
Claude runs in that folder. For browser tools, bind the current tab with the
globe control in the composer.

### If it stays Offline

| Symptom | Fix |
|---|---|
| `/health` times out or connection refused | Bridge not running — start it, or see `~/.dev-bridge/bridge.log` |
| `403` | Token mismatch — paste `cat ~/.dev-bridge/token` again |
| Pip grey, health 200 | CORS — restart bridge with `BRIDGE_EXTENSION_ID=chrome-extension://<id>` |
| `claude not found` | `which claude`; LaunchAgent PATH is small — use `scripts/install-macos-service.sh` |
| `503 Browser client not connected` | Open the side panel and bind a tab |

---

## 4. Run the bridge in the background (macOS)

After the venv is installed:

```bash
chmod +x scripts/install-macos-service.sh
./scripts/install-macos-service.sh
```

This writes `~/Library/LaunchAgents/com.devscope.bridge.plist`, starts at login,
keeps the process alive, raises the open-files limit, and caps orchestrator
workers at 3.

```bash
# logs
tail -f ~/.dev-bridge/bridge.log

# stop
launchctl bootout "gui/$(id -u)/com.devscope.bridge"

# start again
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.devscope.bridge.plist"
```

If you rebuild the Python package, kickstart:

```bash
launchctl kickstart -k "gui/$(id -u)/com.devscope.bridge"
```

On Linux, run `devscope-bridge` under systemd/user or a tmux session. There is
no Linux unit in this snapshot.

---

## 5. MCP tools (browser, WhatsApp, Gmail, …)

Claude only sees browser/WhatsApp/Gmail tools if an MCP config is loaded.

**Option A — this repo as the chat’s project folder**  
`.mcp.json` and `.cursor/mcp.json` already list the DevScope servers. In
DevScope → New chat → Project = this directory.

**Option B — your own repo**  
Copy `.mcp.json` (and optionally `.cursor/mcp.json`) into that project, then
set the chat’s project path to that repo.

**Option C — register globally for the Claude CLI**

```bash
source .venv/bin/activate
python -m devscope_bridge.setup_mcp
claude mcp list
```

Use the **same** Python that has `devscope_bridge` installed. If `.mcp.json`
says `python3 -m devscope_bridge.…`, that `python3` must resolve to the venv
(activate it, or edit `.mcp.json` to `.venv/bin/python`).

### Optional OAuth

```bash
# Gmail
GOOGLE_CLIENT_ID=... GOOGLE_CLIENT_SECRET=... python -m devscope_bridge.gmail.authorize_gmail

# Google Calendar
GOOGLE_CLIENT_ID=... GOOGLE_CLIENT_SECRET=... python -m devscope_bridge.calendar.authorize_calendar

# Meta Ads
FACEBOOK_APP_ID=... FACEBOOK_APP_SECRET=... python -m devscope_bridge.meta_ads.authorize_meta_ads
```

Tokens land in `~/.dev-bridge/` (`gmail_token.json`, `calendar_token.json`,
`meta_ads_token.json`). Never commit them.

---

## Layout

```
devscope_bridge/     Python package (FastAPI bridge + MCP stdio servers)
extension/           Chrome MV3 side panel (Vite)
scripts/             macOS LaunchAgent installer
.mcp.json            Claude Code MCP (this repo)
.cursor/mcp.json     Cursor agent MCP (this repo)
.claude/skills/      Agent playbooks
```

Data on disk (all local):

- `~/.dev-bridge/token`
- `~/.dev-bridge/sessions.json`
- `~/.dev-bridge/bridge.log`
- `~/.dev-bridge/chat-transcripts/`
- `~/.dev-bridge/*.db`

---

## Tests

```bash
source .venv/bin/activate
pip install pytest
pytest
```

Empirical tests that spawn a real `claude` process stay skipped unless
`RUN_EMPIRICAL=1`.

---

## Publish this as its own GitHub repo

This folder is currently nested inside another project. To make it public:

```bash
cd /path/to/devscope
git init
git add .
git commit -m "Initial public snapshot of DevScope"
gh repo create devscope --public --source=. --remote=origin --push
```

Do a search for secrets before the first push (`token`, `.env`, JWT). This
snapshot ships with examples only — no live credentials.

Hebrew step-by-step: [docs/SETUP.he.md](docs/SETUP.he.md)

## Privacy

See [extension/store/privacy-policy.md](extension/store/privacy-policy.md).
