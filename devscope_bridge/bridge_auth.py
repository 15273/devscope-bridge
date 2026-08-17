"""Loopback token auth and session-name validation."""

from __future__ import annotations

import logging
import re
import secrets
import stat
from pathlib import Path

from fastapi import HTTPException, Request, WebSocket

logger = logging.getLogger(__name__)

BRIDGE_DIR = Path.home() / ".dev-bridge"
TOKEN_FILE = BRIDGE_DIR / "token"
SESSION_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def current_token() -> str:
    """Read the live token from main so test monkeypatches keep working."""
    from devscope_bridge import main as bridge_main
    return bridge_main._startup_token


def generate_and_persist_token() -> str:
    """Reuse the existing token if present, else generate + persist a new one.

    Reusing across restarts means the extension's saved token keeps working —
    no need to re-paste it every time the bridge is restarted.
    """
    BRIDGE_DIR.mkdir(parents=True, exist_ok=True)
    if TOKEN_FILE.exists():
        existing = TOKEN_FILE.read_text().strip()
        if existing:
            return existing
    token = secrets.token_hex(32)
    TOKEN_FILE.write_text(token)
    TOKEN_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return token


def extract_token(request: Request) -> str | None:
    qs = request.query_params.get("token")
    if qs:
        return qs
    auth = request.headers.get("Authorization", "")
    return auth[7:] if auth.startswith("Bearer ") else None


def check_auth(request: Request) -> None:
    if extract_token(request) != current_token():
        client = request.client.host if request.client else "unknown"
        logger.warning("Auth mismatch from %s", client)
        raise HTTPException(status_code=403, detail="Invalid token")


def require_auth(request: Request) -> None:
    check_auth(request)


def validate_session_name(name: str) -> str:
    if not SESSION_NAME_RE.match(name):
        raise HTTPException(status_code=422, detail="Invalid session name")
    return name


async def ws_auth(ws: WebSocket) -> bool:
    token = ws.query_params.get("token")
    if not token:
        auth_hdr = ws.headers.get("Authorization", "")
        token = auth_hdr[7:] if auth_hdr.startswith("Bearer ") else None
    if token != current_token():
        logger.warning("WS auth mismatch from %s", ws.client.host if ws.client else "unknown")
        return False
    return True
