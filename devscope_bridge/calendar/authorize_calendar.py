"""authorize_calendar.py — OAuth CLI for Google Calendar read access.

Run once per machine:

    GOOGLE_CLIENT_ID=... GOOGLE_CLIENT_SECRET=... \\
    python -m devscope_bridge.calendar.authorize_calendar

Writes ~/.dev-bridge/calendar_token.json (0600).
"""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path

_SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
]
_TOKEN_FILE = Path.home() / ".dev-bridge" / "calendar_token.json"


def _build_client_config() -> dict:
    client_id = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise RuntimeError(
            "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be set in the environment."
        )
    return {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob", "http://localhost"],
        }
    }


def authorize() -> None:
    from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore[import-untyped]

    config = _build_client_config()
    flow = InstalledAppFlow.from_client_config(config, scopes=_SCOPES)
    creds = flow.run_local_server(port=0)

    _TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    token_data = json.loads(creds.to_json())
    _TOKEN_FILE.write_text(json.dumps(token_data, indent=2))
    _TOKEN_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)
    print(f"Calendar token saved to {_TOKEN_FILE}")


if __name__ == "__main__":
    authorize()
