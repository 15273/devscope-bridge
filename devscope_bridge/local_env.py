"""Load optional local-only env for dev_bridge (never committed)."""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_LOADED = False


def _parse_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if stripped.startswith("export "):
        stripped = stripped[7:].strip()
    if "=" not in stripped:
        return None
    key, _, value = stripped.partition("=")
    key = key.strip()
    value = value.strip().strip("'").strip('"')
    if not key:
        return None
    return key, value


def _load_file(path: Path) -> int:
    count = 0
    for raw in path.read_text(encoding="utf-8").splitlines():
        parsed = _parse_line(raw)
        if parsed is None:
            continue
        key, value = parsed
        if key not in os.environ:
            os.environ[key] = value
            count += 1
    return count


def load_local_env() -> None:
    """Load ~/.dev-bridge/local.env and devscope_bridge/.env.local (first wins per key)."""
    global _LOADED
    if _LOADED:
        return
    _LOADED = True
    candidates = [
        Path.home() / ".dev-bridge" / "local.env",
        Path(__file__).resolve().parent / ".env.local",
    ]
    for path in candidates:
        if not path.is_file():
            continue
        try:
            n = _load_file(path)
            logger.info("loaded %d env vars from %s", n, path)
        except OSError as exc:
            logger.warning("could not read %s: %s", path, exc)
