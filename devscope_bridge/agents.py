"""Canonical agent slugs shared by HTTP, store, spawn, and schedules."""

from __future__ import annotations

VALID_AGENTS = frozenset({"claude", "cursor", "codex", "antigravity"})
ONESHOT_AGENTS = frozenset({"cursor", "codex", "antigravity"})
KEEP_ID_ON_RESET = ONESHOT_AGENTS

AGENT_LABELS = {
    "claude": "Claude",
    "cursor": "Cursor",
    "codex": "Codex",
    "antigravity": "Antigravity",
}

SOURCE_CODEX = "codex"
SOURCE_ANTIGRAVITY_CLI = "antigravity_cli"
SOURCE_ANTIGRAVITY_IDE = "antigravity_ide"


def parse_agent(value: object, fallback: str = "claude") -> str:
    if isinstance(value, str) and value in VALID_AGENTS:
        return value
    return fallback


def agent_label(agent: str) -> str:
    return AGENT_LABELS.get(parse_agent(agent), AGENT_LABELS["claude"])


def is_oneshot_agent(agent: str) -> bool:
    return parse_agent(agent) in ONESHOT_AGENTS


def keep_session_id_on_reset(agent: str) -> bool:
    return parse_agent(agent) in KEEP_ID_ON_RESET
