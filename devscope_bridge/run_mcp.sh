#!/usr/bin/env bash
# Launch a DevScope MCP server from repo-root venv (cwd-independent).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODULE="${DEVSCOPE_MCP_MODULE:-devscope_bridge.browser_mcp_server}"
PYTHON="${ROOT}/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="$(command -v python3)"
fi
exec "$PYTHON" -m "$MODULE"
