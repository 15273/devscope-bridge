#!/usr/bin/env python3
"""
setup_mcp.py — one-shot: register DevScope MCP servers with Claude Code (local scope).

Reads repo .mcp.json and runs `claude mcp add` for each DevScope server.
Skip servers already registered. Safe to re-run.

Usage (from repo root):
  .venv/bin/python -m devscope_bridge.setup_mcp
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MCP_JSON = REPO_ROOT / ".mcp.json"

DEVSCOPE_SERVER_IDS = frozenset({
    "browser-control",
    "whatsapp-control",
    "gmail-control",
    "calendar-control",
    "task-control",
    "devscope-control",
    "meta-ads-control",
})


def _claude_bin() -> str:
    claude = shutil.which("claude")
    if not claude:
        raise SystemExit("claude CLI not found on PATH — install from https://claude.ai/download")
    return claude


def _list_registered() -> set[str]:
    claude = _claude_bin()
    try:
        out = subprocess.check_output([claude, "mcp", "list"], text=True, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as exc:
        print(exc.output or exc, file=sys.stderr)
        return set()
    names: set[str] = set()
    for line in out.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # "browser-control: connected" or similar
        name = line.split(":", 1)[0].strip()
        if name:
            names.add(name)
    return names


def _build_add_argv(server_id: str, spec: dict) -> list[str]:
    claude = _claude_bin()
    cmd = spec.get("command", "")
    args = spec.get("args") or []
    if not cmd:
        raise ValueError(f"{server_id}: missing command in .mcp.json")

    # Resolve relative python path against repo root.
    if cmd == ".venv/bin/python":
        cmd = str(REPO_ROOT / ".venv/bin/python")
    elif cmd.endswith("python") and not Path(cmd).is_absolute():
        resolved = REPO_ROOT / cmd
        if resolved.exists():
            cmd = str(resolved)

    argv = [claude, "mcp", "add", "--transport", "stdio", "--scope", "local", server_id, "--", cmd]
    argv.extend(str(a) for a in args)
    return argv


def main() -> None:
    if not MCP_JSON.is_file():
        raise SystemExit(f"Missing {MCP_JSON}")

    data = json.loads(MCP_JSON.read_text())
    servers: dict = data.get("mcpServers") or {}
    registered = _list_registered()

    added = 0
    skipped = 0
    for sid in sorted(DEVSCOPE_SERVER_IDS):
        if sid not in servers:
            print(f"skip {sid}: not in .mcp.json")
            continue
        if sid in registered:
            print(f"ok   {sid}: already registered")
            skipped += 1
            continue
        argv = _build_add_argv(sid, servers[sid])
        print(f"add  {sid}: {' '.join(argv[6:])}")
        subprocess.check_call(argv, cwd=str(REPO_ROOT))
        added += 1

    print(f"\nDone — added {added}, skipped {skipped}. Verify: claude mcp list")


if __name__ == "__main__":
    main()
