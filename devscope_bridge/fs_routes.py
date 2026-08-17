"""
fs_routes.py — filesystem helpers the extension cannot do itself.

GET /fs/list-dirs?path= — list subdirectories for the in-panel folder picker
(the browser sandbox cannot browse real paths; native macOS dialogs from a
background daemon are unreliable, so the panel renders its own picker).
"""

from __future__ import annotations

import base64
import re
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(prefix="/fs", tags=["fs"])

_MAX_ENTRIES = 300
_OUTBOX_ROOT = Path.home() / ".dev-bridge" / "outbox"
_SESSION_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
_DATA_URL_RE = re.compile(r"^data:(image/[\w.+-]+);base64,(.+)$", re.DOTALL)


class OutboxWriteBody(BaseModel):
    filename: str = Field(min_length=1, max_length=120)
    data_url: str = Field(min_length=1)


@router.post("/outbox/{session_name}")
async def write_outbox(session_name: str, body: OutboxWriteBody) -> dict:
    """Save a base64 data URL into ~/.dev-bridge/outbox/{session}/ for PTY turns."""
    if not _SESSION_NAME_RE.match(session_name):
        return {"ok": False, "error": "invalid session name"}
    safe_name = Path(body.filename).name
    if not safe_name or safe_name.startswith("."):
        return {"ok": False, "error": "invalid filename"}
    match = _DATA_URL_RE.match(body.data_url.strip())
    if not match:
        return {"ok": False, "error": "expected image data URL"}
    ext = ".png" if "png" in match.group(1) else ".jpg"
    if not safe_name.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
        safe_name = f"{safe_name}{ext}"
    dest_dir = (_OUTBOX_ROOT / session_name).resolve()
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = (dest_dir / safe_name).resolve()
    if dest.parent != dest_dir:
        return {"ok": False, "error": "path escape blocked"}
    try:
        dest.write_bytes(base64.b64decode(match.group(2), validate=True))
    except (OSError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "path": str(dest)}


@router.get("/list-dirs")
async def list_dirs(path: str = "") -> dict:
    """Subdirectories of ``path`` (default: home). Hidden dirs are skipped."""
    base = Path(path).expanduser() if path.strip() else Path.home()
    try:
        base = base.resolve()
        if not base.is_dir():
            return {"ok": False, "error": f"not a directory: {base}"}
        dirs = []
        for entry in sorted(base.iterdir(), key=lambda p: p.name.lower()):
            if entry.name.startswith("."):
                continue
            try:
                if entry.is_dir() and not entry.is_symlink():
                    dirs.append({"name": entry.name, "path": str(entry)})
            except OSError:
                continue
            if len(dirs) >= _MAX_ENTRIES:
                break
    except (OSError, PermissionError) as exc:
        return {"ok": False, "error": str(exc)}
    parent = str(base.parent) if base != base.parent else None
    return {"ok": True, "path": str(base), "parent": parent, "dirs": dirs}
