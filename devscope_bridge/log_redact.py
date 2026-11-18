"""Redact Bearer tokens and token query params from logs and printed text.

The bridge token lives in ~/.dev-bridge/token (mode 0600). It must never appear
in stdout, uvicorn access lines, or bridge.log. Call set_known_token() once at
startup so exact-value replacements work even if the token is logged without a
Bearer/query prefix.
"""

from __future__ import annotations

import logging
import re
from typing import Any

_BEARER_RE = re.compile(r"(Bearer\s+)(\S+)", re.IGNORECASE)
_QUERY_TOKEN_RE = re.compile(r"([?&](?:token|access_token|auth)=)([^&\s]+)", re.IGNORECASE)
_AUTH_HEADER_RE = re.compile(
    r"(Authorization['\"]?\s*[:=]\s*['\"]?Bearer\s+)(\S+)",
    re.IGNORECASE,
)

_known_tokens: set[str] = set()


def set_known_token(token: str | None) -> None:
    """Register the live bridge token so logs can redact it even without a prefix."""
    _known_tokens.clear()
    if token:
        _known_tokens.add(token)


# Bridge tokens are token_hex(32) (64 chars). Never treat format
# placeholders (%s, {token}) or already-redacted values as secrets.
_MIN_TOKEN_LEN = 8


def _redact_group(match: re.Match[str]) -> str:
    value = match.group(2).rstrip("\"',;")
    if (
        len(value) < _MIN_TOKEN_LEN
        or value.startswith("[redacted")
        or value.startswith("%")
        or value.startswith("{")
    ):
        return match.group(0)
    return f"{match.group(1)}[redacted token len={len(value)}]"


def redact_secrets(text: str) -> str:
    """Return *text* with bearer tokens, token query params, and known tokens removed."""
    if not text:
        return text
    out = text
    for token in list(_known_tokens):
        if token and len(token) >= _MIN_TOKEN_LEN and token in out:
            out = out.replace(token, f"[redacted token len={len(token)}]")
    out = _AUTH_HEADER_RE.sub(_redact_group, out)
    out = _BEARER_RE.sub(_redact_group, out)
    out = _QUERY_TOKEN_RE.sub(_redact_group, out)
    return out


def redact_url_query(url: str) -> str:
    """Strip query and fragment from a URL so health/tab listings cannot leak tokens."""
    if not url:
        return url
    for sep in ("?", "#"):
        cut = url.find(sep)
        if cut != -1:
            url = url[:cut]
    return url


class RedactingFilter(logging.Filter):
    """Logging filter that redacts tokens in msg and args."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if isinstance(record.msg, str):
                record.msg = redact_secrets(record.msg)
            if record.args:
                if isinstance(record.args, dict):
                    record.args = {
                        k: redact_secrets(v) if isinstance(v, str) else v
                        for k, v in record.args.items()
                    }
                elif isinstance(record.args, tuple):
                    record.args = tuple(
                        redact_secrets(a) if isinstance(a, str) else a
                        for a in record.args
                    )
        except Exception:
            # Never break logging because redaction failed.
            pass
        return True


def install_redacting_filter(logger: logging.Logger | None = None) -> RedactingFilter:
    """Attach a process-wide redacting filter to *logger* (root if omitted)."""
    filt = RedactingFilter()
    target = logger or logging.getLogger()
    target.addFilter(filt)
    for handler in target.handlers:
        handler.addFilter(filt)
    # uvicorn loggers do not always propagate to root
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error", "uvicorn.asgi"):
        uv = logging.getLogger(name)
        uv.addFilter(filt)
        for handler in uv.handlers:
            handler.addFilter(filt)
    return filt
