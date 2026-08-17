# Setup & Connection — DevScope (macOS)

גרסה בעברית: [SETUP.he.md](SETUP.he.md)

DevScope = a Chrome extension + a local server (the bridge) on `127.0.0.1:7878`.
The agent is the Claude CLI you already have installed. There is no DevScope cloud.

This folder is self-contained. It does not depend on any other product.

---

## Requirements

1. Python 3.11 or newer (`python3 --version`)
2. Node 18+ (`node --version`) — only for the first build of the extension
3. Claude CLI, logged in:

   ```bash
   which claude
   claude login
   ```

4. Chrome

---

## Step 1 — Install the bridge

Open a terminal **inside the `devscope` folder**:

```bash
cd /path/to/devscope
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Run it once in the foreground (for the first connection):

```bash
devscope-bridge
```

You should see:

```
Dev Bridge started. Token: …
```

In another window:

```bash
curl http://127.0.0.1:7878/health
```

If you get JSON with `"ok": true` — the bridge is alive. Keep the process
running through the end of step 3, or skip ahead to step 4.

The token is written to `~/.dev-bridge/token` and stays the same across restarts.

---

## Step 2 — Build the extension and load it in Chrome

```bash
cd /path/to/devscope/extension
npm install
npm run build
```

The output is `extension/dist/`.

In Chrome:

1. Go to `chrome://extensions`
2. Enable **Developer mode**
3. **Load unpacked** → select the **`dist`** folder (not `src`)
4. Copy the extension **ID** (32 characters, shown on the card)

Clicking the icon opens the side panel.

---

## Step 3 — Connect the extension to the bridge

Stop the bridge (Ctrl+C) and restart it **with the extension ID** — otherwise
CORS blocks the connection:

```bash
cd /path/to/devscope
source .venv/bin/activate
export BRIDGE_EXTENSION_ID="chrome-extension://PASTE_ID"
devscope-bridge
```

In the side panel:

1. Gear icon (Settings)
2. Paste the token:

   ```bash
   cat ~/.dev-bridge/token
   ```

3. Save / Test connection

The connection pip should turn **green**.

**First chat:** New chat → pick a project folder (your code) → send a message.
For the agent to act in the browser, bind a tab (the globe control in the composer).

---

## Step 4 — Run in the background (recommended on Mac)

Once `.venv` exists:

```bash
cd /path/to/devscope
chmod +x scripts/install-macos-service.sh
./scripts/install-macos-service.sh
```

What it does:

- Writes `~/Library/LaunchAgents/com.devscope.bridge.plist`
- Starts at login
- KeepAlive
- Log: `~/.dev-bridge/bridge.log`

```bash
# live log
tail -f ~/.dev-bridge/bridge.log

# stop
launchctl bootout "gui/$(id -u)/com.devscope.bridge"

# restart after a code change
launchctl kickstart -k "gui/$(id -u)/com.devscope.bridge"
```

If `/health` doesn't answer after a few seconds — read the log. Never run
`uvicorn --workers 2`. One process only.

---

## Step 5 — MCP tools (browser / WhatsApp / Gmail)

Claude only sees the tools if the chat's project has a `.mcp.json`, **or**
after registering them globally.

**Simplest:** in New chat, pick the `devscope` folder itself as the project
(it ships with `.mcp.json`).

**Or** copy `.mcp.json` into your own project folder.

Global registration:

```bash
cd /path/to/devscope
source .venv/bin/activate
python -m devscope_bridge.setup_mcp
claude mcp list
```

Important: the `python3` referenced in `.mcp.json` must be the same Python that
has `devscope_bridge` installed (hence `source .venv/bin/activate`). If it
isn't — change `command` in `.mcp.json` to `/path/to/devscope/.venv/bin/python`.

Optional OAuth:

```bash
GOOGLE_CLIENT_ID=... GOOGLE_CLIENT_SECRET=... python -m devscope_bridge.gmail.authorize_gmail
GOOGLE_CLIENT_ID=... GOOGLE_CLIENT_SECRET=... python -m devscope_bridge.calendar.authorize_calendar
```

Tokens are stored under `~/.dev-bridge/` and never enter git.

---

## Common problems

| Symptom | Fix |
|---|---|
| Connection refused on `:7878` | Bridge not running. Run `devscope-bridge`, or kickstart the LaunchAgent |
| Health hangs / Offline even though it's running | Check `~/.dev-bridge/bridge.log`, then kickstart |
| 403 | Token in the extension doesn't match — paste it again from `~/.dev-bridge/token` |
| Pip grey, health 200 | `BRIDGE_EXTENSION_ID` missing — restart with the ID |
| `claude: command not found` | Claude isn't on the bridge process PATH. Install via `scripts/install-macos-service.sh` |
| `503 Browser client not connected` | Open the side panel and bind a tab |
| Rebuilt the extension but see no change | In `chrome://extensions`, hit Reload on the DevScope card |

---

## Publishing as a public repo

```bash
cd /path/to/devscope
git init
git add .
git status    # make sure no .env / token / secrets are staged
git commit -m "Initial public snapshot of DevScope"
gh repo create devscope --public --source=. --remote=origin --push
```

Before pushing, search for `token` / `eyJ` / passwords. This snapshot contains
no live credentials.
