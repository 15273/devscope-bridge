"""
employee_config.py — settings for the Autonomous Employee layer.

Persisted at ~/.dev-bridge/employee_config.json. Everything defaults OFF so a
fresh install behaves exactly like today's orchestrator. Loaded generically
({**DEFAULTS, **raw}) so adding fields never needs migration code.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path.home() / ".dev-bridge" / "employee_config.json"

DEFAULT_CHANNELS: dict[str, bool] = {
    "panel": True,
    "notion": False,
    "whatsapp": False,
    "email": False,
}


@dataclass
class EmployeeSettings:
    employee_enabled: bool = False          # master switch for the whole layer
    board_provider: str = "notion"
    board_database: str = ""                # Notion database name or URL
    board_sync_enabled: bool = False
    board_sync_every_ticks: int = 3
    board_push_max_per_sync: int = 5
    channels: dict[str, bool] = field(default_factory=lambda: dict(DEFAULT_CHANNELS))
    wa_chat_id: str = ""
    digest_email: str = ""                  # empty → send to the authenticated account
    digest_daily_at: str = "18:00"

    def clamp(self) -> "EmployeeSettings":
        self.board_sync_every_ticks = max(1, min(48, int(self.board_sync_every_ticks)))
        self.board_push_max_per_sync = max(1, min(25, int(self.board_push_max_per_sync)))
        self.channels = {**DEFAULT_CHANNELS,
                         **{k: bool(v) for k, v in (self.channels or {}).items()}}
        return self


def _field_names() -> set[str]:
    return set(EmployeeSettings.__dataclass_fields__)


def load() -> EmployeeSettings:
    try:
        raw = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return EmployeeSettings()
    known = {k: v for k, v in raw.items() if k in _field_names()}
    try:
        return EmployeeSettings(**known).clamp()
    except (TypeError, ValueError):
        logger.warning("invalid employee_config.json — using defaults")
        return EmployeeSettings()


def save(settings: EmployeeSettings) -> None:
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_PATH.write_text(
        json.dumps(asdict(settings.clamp()), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def patch(fields: dict) -> EmployeeSettings:
    """Merge a partial update into the stored settings and return the result."""
    current = asdict(load())
    for key, value in fields.items():
        if key not in _field_names() or value is None:
            continue
        if key == "channels" and isinstance(value, dict):
            current["channels"] = {**current["channels"], **value}
        else:
            current[key] = value
    settings = EmployeeSettings(**current).clamp()
    save(settings)
    return settings
