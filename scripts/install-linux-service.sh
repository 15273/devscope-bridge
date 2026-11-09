#!/usr/bin/env bash
# Install DevScope bridge as a systemd --user unit (Linux).
# Run from the cloned repo after: python3 -m venv .venv && .venv/bin/pip install -e .
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${ROOT}/.venv/bin/python"
UNIT_NAME="devscope-bridge.service"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT_PATH="${UNIT_DIR}/${UNIT_NAME}"

if [[ ! -x "$PYTHON" ]]; then
  echo "Missing $PYTHON"
  echo "Create it first:"
  echo "  cd \"$ROOT\" && python3 -m venv .venv && .venv/bin/pip install -e ."
  exit 1
fi

if ! command -v systemctl >/dev/null 2>&1; then
  echo "systemctl not found — install systemd or run the bridge in the foreground / tmux."
  exit 1
fi

mkdir -p "$UNIT_DIR" "${HOME}/.dev-bridge"

PATH_VALUE="${HOME}/.local/bin:/usr/local/bin:/usr/bin:/bin:${PATH}"

cat > "$UNIT_PATH" <<UNIT
[Unit]
Description=DevScope local bridge (loopback FastAPI on 127.0.0.1:7878)
After=default.target

[Service]
Type=simple
WorkingDirectory=${ROOT}
ExecStart=${PYTHON} -m devscope_bridge.main
Restart=on-failure
RestartSec=3
Environment=PATH=${PATH_VALUE}
Environment=ORCHESTRATOR_MAX_WORKERS=3
LimitNOFILE=65536
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
UNIT

systemctl --user daemon-reload
systemctl --user enable --now "$UNIT_NAME"

echo "Installed ${UNIT_PATH}"
echo "Health check:"
sleep 1
curl -sS --max-time 5 http://127.0.0.1:7878/health || echo "(not answering yet — check: journalctl --user -u ${UNIT_NAME} -n 50)"
echo
echo "Token:  cat ~/.dev-bridge/token"
echo "Logs:   journalctl --user -u ${UNIT_NAME} -f"
echo "Stop:   systemctl --user stop ${UNIT_NAME}"
echo "Start:  systemctl --user start ${UNIT_NAME}"
