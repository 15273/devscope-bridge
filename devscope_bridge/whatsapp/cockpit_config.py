"""Cockpit scope config at ~/.dev-bridge/wa_cockpit_config.json.

Controls which chats produce 'forgot to reply' nudges and how stale a chat must
be before it counts.
"""
from __future__ import annotations

import json
from pathlib import Path

DEFAULT = {
    "threshold_hours": 3,
    "dm_in_scope": True,
    "group_allowlist": [],
    "blacklist": [],
    "poll_interval_s": 300,
}


def load(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        return {**DEFAULT, "group_allowlist": [], "blacklist": []}
    data = json.loads(p.read_text("utf-8"))
    return {**DEFAULT, **data}


def save(path: str | Path, cfg: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), "utf-8")


def is_in_scope(cfg: dict, chat_id: str, *, is_group: bool) -> bool:
    if chat_id in cfg.get("blacklist", []):
        return False
    if is_group:
        return chat_id in cfg.get("group_allowlist", [])
    return bool(cfg.get("dm_in_scope", True))
