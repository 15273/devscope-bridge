"""Persisted orchestrator settings at ~/.dev-bridge/orchestrator_config.json."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from devscope_bridge import agent_policies

logger = logging.getLogger(__name__)

CONFIG_PATH = Path.home() / ".dev-bridge" / "orchestrator_config.json"

DEFAULTS = {
    "tick_seconds": int(os.environ.get("ORCHESTRATOR_TICK_SECONDS", "720")),
    "max_workers": int(os.environ.get("ORCHESTRATOR_MAX_WORKERS", "3")),
    "quota_throttle_enabled": True,
    "quota_high_utilization": 80,
    "quota_mid_utilization": 60,
    "paused": False,
    "auto_hygiene_enabled": True,
    "recovery_backlog_cap": 50,
    "worker_session_cap": 80,
    "auto_pause_utilization": 85,
    "auto_pause_min_queued": 75,
    "hygiene_interval_seconds": 300,
    "chat_auto_compact_enabled": True,
    "chat_auto_compact_turns": 28,
    "chat_auto_compact_total_tokens": 800_000,
    "chat_auto_compact_context_tokens": 140_000,
    "chat_warn_turns": 8,
    "chat_warn_total_tokens": 120_000,
    "chat_warn_context_tokens": 60_000,
    "chat_suggest_sonnet_on_opus": True,
}


@dataclass
class OrchestratorConfig:
    tick_seconds: int = DEFAULTS["tick_seconds"]
    max_workers: int = DEFAULTS["max_workers"]
    domains: tuple[str, ...] = agent_policies.DOMAINS


@dataclass
class OrchestratorSettings:
    tick_seconds: int = DEFAULTS["tick_seconds"]
    max_workers: int = DEFAULTS["max_workers"]
    quota_throttle_enabled: bool = True
    quota_high_utilization: int = 80
    quota_mid_utilization: int = 60
    paused: bool = False
    auto_hygiene_enabled: bool = True
    recovery_backlog_cap: int = 50
    worker_session_cap: int = 80
    auto_pause_utilization: int = 85
    auto_pause_min_queued: int = 75
    hygiene_interval_seconds: int = 300
    chat_auto_compact_enabled: bool = True
    chat_auto_compact_turns: int = 28
    chat_auto_compact_total_tokens: int = 800_000
    chat_auto_compact_context_tokens: int = 140_000
    chat_warn_turns: int = 8
    chat_warn_total_tokens: int = 120_000
    chat_warn_context_tokens: int = 60_000
    chat_suggest_sonnet_on_opus: bool = True

    def to_config(self) -> OrchestratorConfig:
        return OrchestratorConfig(
            tick_seconds=max(30, self.tick_seconds),
            max_workers=max(1, min(16, self.max_workers)),
        )

    def clamp(self) -> OrchestratorSettings:
        return OrchestratorSettings(
            tick_seconds=max(30, min(3600, self.tick_seconds)),
            max_workers=max(1, min(16, self.max_workers)),
            quota_throttle_enabled=self.quota_throttle_enabled,
            quota_high_utilization=max(50, min(99, self.quota_high_utilization)),
            quota_mid_utilization=max(20, min(98, self.quota_mid_utilization)),
            paused=bool(self.paused),
            auto_hygiene_enabled=bool(self.auto_hygiene_enabled),
            recovery_backlog_cap=max(0, min(500, self.recovery_backlog_cap)),
            worker_session_cap=max(10, min(500, self.worker_session_cap)),
            auto_pause_utilization=max(0, min(99, self.auto_pause_utilization)),
            auto_pause_min_queued=max(0, min(5000, self.auto_pause_min_queued)),
            hygiene_interval_seconds=max(60, min(3600, self.hygiene_interval_seconds)),
            chat_auto_compact_enabled=bool(self.chat_auto_compact_enabled),
            chat_auto_compact_turns=max(5, min(100, self.chat_auto_compact_turns)),
            chat_auto_compact_total_tokens=max(50_000, min(10_000_000, self.chat_auto_compact_total_tokens)),
            chat_auto_compact_context_tokens=max(20_000, min(500_000, self.chat_auto_compact_context_tokens)),
            chat_warn_turns=max(3, min(50, self.chat_warn_turns)),
            chat_warn_total_tokens=max(20_000, min(5_000_000, self.chat_warn_total_tokens)),
            chat_warn_context_tokens=max(10_000, min(300_000, self.chat_warn_context_tokens)),
            chat_suggest_sonnet_on_opus=bool(self.chat_suggest_sonnet_on_opus),
        )


def load() -> OrchestratorSettings:
    if not CONFIG_PATH.exists():
        return OrchestratorSettings(**DEFAULTS).clamp()
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("orchestrator config unreadable (%s) — using defaults", exc)
        return OrchestratorSettings(**DEFAULTS).clamp()
    merged = {**DEFAULTS, **raw}
    return OrchestratorSettings(
        tick_seconds=int(merged["tick_seconds"]),
        max_workers=int(merged["max_workers"]),
        quota_throttle_enabled=bool(merged.get("quota_throttle_enabled", True)),
        quota_high_utilization=int(merged.get("quota_high_utilization", 80)),
        quota_mid_utilization=int(merged.get("quota_mid_utilization", 60)),
        paused=bool(merged.get("paused", False)),
        auto_hygiene_enabled=bool(merged.get("auto_hygiene_enabled", True)),
        recovery_backlog_cap=int(merged.get("recovery_backlog_cap", 50)),
        worker_session_cap=int(merged.get("worker_session_cap", 80)),
        auto_pause_utilization=int(merged.get("auto_pause_utilization", 85)),
        auto_pause_min_queued=int(merged.get("auto_pause_min_queued", 75)),
        hygiene_interval_seconds=int(merged.get("hygiene_interval_seconds", 300)),
        chat_auto_compact_enabled=bool(merged.get("chat_auto_compact_enabled", True)),
        chat_auto_compact_turns=int(merged.get("chat_auto_compact_turns", 28)),
        chat_auto_compact_total_tokens=int(merged.get("chat_auto_compact_total_tokens", 800_000)),
        chat_auto_compact_context_tokens=int(merged.get("chat_auto_compact_context_tokens", 140_000)),
        chat_warn_turns=int(merged.get("chat_warn_turns", 8)),
        chat_warn_total_tokens=int(merged.get("chat_warn_total_tokens", 120_000)),
        chat_warn_context_tokens=int(merged.get("chat_warn_context_tokens", 60_000)),
        chat_suggest_sonnet_on_opus=bool(merged.get("chat_suggest_sonnet_on_opus", True)),
    ).clamp()


def save(settings: OrchestratorSettings) -> OrchestratorSettings:
    settings = settings.clamp()
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps(asdict(settings), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    logger.info("orchestrator config saved: tick=%ss max_workers=%d",
                settings.tick_seconds, settings.max_workers)
    return settings
