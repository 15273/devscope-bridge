# DevScope Chrome extension

Side panel UI that talks to the local **devscope-bridge** on `127.0.0.1:7878`.

## Build

```bash
cd extension
npm install
npm run build    # writes dist/
```

## Load in Chrome

1. Open `chrome://extensions`
2. Enable **Developer mode**
3. **Load unpacked** → select `extension/dist/`
4. Copy the extension ID from the card (32 characters)

## Connect

Start the bridge with that ID:

```bash
export BRIDGE_EXTENSION_ID="chrome-extension://<the-id>"
devscope-bridge
```

Paste `~/.dev-bridge/token` into **Settings → Bridge token**. The header pip turns green when the WebSocket is live.

## Watch mode

```bash
npm run dev   # rebuild on change; click Reload on the extension card after each build
```
