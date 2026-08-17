#!/usr/bin/env bash
# Install DevScope bridge as a user LaunchAgent (macOS).
# Run from the cloned repo after: python3 -m venv .venv && .venv/bin/pip install -e .
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${ROOT}/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  echo "Missing $PYTHON"
  echo "Create it first:"
  echo "  cd \"$ROOT\" && python3 -m venv .venv && .venv/bin/pip install -e ."
  exit 1
fi

LABEL="com.devscope.bridge"
PLIST="${HOME}/Library/LaunchAgents/${LABEL}.plist"
UID_NUM="$(id -u)"
LOG_DIR="${HOME}/.dev-bridge"
mkdir -p "$LOG_DIR" "${HOME}/Library/LaunchAgents"

# claude / cursor-agent must be on PATH inside launchd (it has a tiny default PATH).
PATH_VALUE="${HOME}/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH}"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${PYTHON}</string>
        <string>-m</string>
        <string>devscope_bridge.main</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${ROOT}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>SoftResourceLimits</key>
    <dict>
        <key>NumberOfFiles</key>
        <integer>65536</integer>
    </dict>
    <key>HardResourceLimits</key>
    <dict>
        <key>NumberOfFiles</key>
        <integer>65536</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>${LOG_DIR}/bridge.log</string>
    <key>StandardErrorPath</key>
    <string>${LOG_DIR}/bridge.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>ORCHESTRATOR_MAX_WORKERS</key>
        <string>3</string>
        <key>PATH</key>
        <string>${PATH_VALUE}</string>
    </dict>
</dict>
</plist>
EOF

launchctl bootout "gui/${UID_NUM}/${LABEL}" 2>/dev/null || true
launchctl bootstrap "gui/${UID_NUM}" "$PLIST"
launchctl kickstart -k "gui/${UID_NUM}/${LABEL}"

echo "Installed ${PLIST}"
echo "Health check:"
sleep 1
curl -sS --max-time 5 http://127.0.0.1:7878/health || echo "(not answering yet — check ${LOG_DIR}/bridge.log)"
echo
echo "Token:  cat ~/.dev-bridge/token"
echo "Logs:   tail -f ${LOG_DIR}/bridge.log"
echo "Stop:   launchctl bootout gui/${UID_NUM}/${LABEL}"
echo "Start:  launchctl bootstrap gui/${UID_NUM} ${PLIST} && launchctl kickstart -k gui/${UID_NUM}/${LABEL}"
