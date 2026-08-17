"""authorize_meta_ads.py — OAuth CLI for Meta Marketing API.

Writes ~/.dev-bridge/meta_ads_token.json (0600).

    FACEBOOK_APP_ID=... FACEBOOK_APP_SECRET=... \\
    python -m devscope_bridge.meta_ads.authorize_meta_ads
"""
from __future__ import annotations

import json
import os
import stat
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx

_TOKEN_FILE = Path.home() / ".dev-bridge" / "meta_ads_token.json"
_REDIRECT_URI = "http://localhost:8765/callback"
_SCOPES = "ads_read,ads_management,business_management"
_GRAPH_VERSION = os.environ.get("FACEBOOK_GRAPH_VERSION", "v21.0").strip()


def _app_credentials() -> tuple[str, str]:
    app_id = (
        os.environ.get("FACEBOOK_APP_ID")
        or os.environ.get("META_APP_ID")
        or ""
    ).strip()
    secret = (
        os.environ.get("FACEBOOK_APP_SECRET")
        or os.environ.get("META_APP_SECRET")
        or ""
    ).strip()
    if not app_id or not secret:
        raise RuntimeError(
            "FACEBOOK_APP_ID and FACEBOOK_APP_SECRET must be set in the environment."
        )
    return app_id, secret


def _exchange_code(app_id: str, secret: str, code: str) -> dict:
    with httpx.Client(timeout=30.0) as client:
        short = client.get(
            f"https://graph.facebook.com/{_GRAPH_VERSION}/oauth/access_token",
            params={
                "client_id": app_id,
                "client_secret": secret,
                "redirect_uri": _REDIRECT_URI,
                "code": code,
            },
        )
        short.raise_for_status()
        data = short.json()
        token = data.get("access_token")
        if not token:
            raise RuntimeError(f"No access_token in response: {data}")

        long_resp = client.get(
            f"https://graph.facebook.com/{_GRAPH_VERSION}/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": app_id,
                "client_secret": secret,
                "fb_exchange_token": token,
            },
        )
        long_resp.raise_for_status()
        long_data = long_resp.json()
        if long_data.get("access_token"):
            data = long_data
        return data


def authorize() -> None:
    app_id, secret = _app_credentials()
    auth_url = (
        f"https://www.facebook.com/{_GRAPH_VERSION}/dialog/oauth?"
        f"client_id={app_id}&redirect_uri={_REDIRECT_URI}"
        f"&scope={_SCOPES}&response_type=code"
    )
    code_holder: dict[str, str] = {}

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args) -> None:
            return

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path != "/callback":
                self.send_response(404)
                self.end_headers()
                return
            qs = parse_qs(parsed.query)
            if "error" in qs:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(qs["error"][0].encode())
                return
            code = qs.get("code", [None])[0]
            if not code:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"missing code")
                return
            code_holder["code"] = code
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Meta Ads authorization complete. You can close this tab.")

    print(f"Open this URL if the browser does not start:\n{auth_url}\n")
    webbrowser.open(auth_url)
    server = HTTPServer(("127.0.0.1", 8765), _Handler)
    while "code" not in code_holder:
        server.handle_request()
    server.server_close()

    token_data = _exchange_code(app_id, secret, code_holder["code"])
    token_data.setdefault("default_ad_account_id", None)
    _TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    _TOKEN_FILE.write_text(json.dumps(token_data, indent=2))
    _TOKEN_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)
    print(f"Token saved to {_TOKEN_FILE}")


if __name__ == "__main__":
    authorize()
