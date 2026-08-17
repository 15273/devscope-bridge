"""Locate DevScope repo root for cursor-agent --workspace and MCP config."""

from __future__ import annotations

import os
from pathlib import Path

_MARKER = Path(".cursor") / "mcp.json"


def find_devscope_workspace(start_cwd: str) -> str | None:
    """Walk up from start_cwd until .cursor/mcp.json is found."""
    try:
        current = Path(start_cwd).resolve()
    except OSError:
        return None
    for candidate in (current, *current.parents):
        if (candidate / _MARKER).is_file():
            return str(candidate)
    override = os.environ.get("DEVSCOPE_REPO_ROOT", "").strip()
    if override and (Path(override) / _MARKER).is_file():
        return str(Path(override).resolve())
    return None
