"""authorize_gmail.py — one-shot CLI that runs the Gmail OAuth flow and writes
the token to ~/.dev-bridge/gmail_token.json.

Run once per machine (or after token expiry):

    python -m devscope_bridge.gmail.authorize_gmail

Requires env vars:
    GOOGLE_CLIENT_ID     — OAuth 2.0 client ID (web or installed-app type)
    GOOGLE_CLIENT_SECRET — matching client secret

The flow opens a local server on a random port; your browser will redirect
there after you grant access. The resulting token is persisted and reused
automatically by gmail_service._client().
"""
import json
import os
import stat
from pathlib import Path

_SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
_TOKEN_FILE = Path.home() / ".dev-bridge" / "gmail_token.json"


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
    """Run the installed-app OAuth flow and persist the token."""
    from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore[import-untyped]

    config = _build_client_config()
    flow = InstalledAppFlow.from_client_config(config, scopes=_SCOPES)
    creds = flow.run_local_server(port=0)

    _TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    token_data = json.loads(creds.to_json())
    _TOKEN_FILE.write_text(json.dumps(token_data, indent=2))
    _TOKEN_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)
    print(f"Token saved to {_TOKEN_FILE}")


if __name__ == "__main__":
    authorize()
