"""
board_state.py — Ephemeral orchestrator UI state (tick timing, MoM report).

Persisted in ~/.dev-bridge/board_state.json — not authoritative task data.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

_STATE_PATH = Path.home() / ".dev-bridge" / "board_state.json"
_TS_FMT = "%Y-%m-%d %H:%M:%S"


@dataclass
class BoardState:
    last_tick_at: str | None = None
    next_tick_at: str | None = None
    last_mom_report: str | None = None
    last_mom_report_at: str | None = None
    tick_seconds: int = 720

    def snapshot(self) -> dict:
        return asdict(self)


def _now() -> str:
    return datetime.now().strftime(_TS_FMT)


def load() -> BoardState:
    if not _STATE_PATH.exists():
        return BoardState()
    try:
        data = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
        return BoardState(**{k: data[k] for k in asdict(BoardState()) if k in data})
    except Exception:
        logger.debug("board_state load failed", exc_info=True)
        return BoardState()


def save(state: BoardState) -> None:
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STATE_PATH.write_text(
        json.dumps(state.snapshot(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def mark_tick_start(tick_seconds: int) -> BoardState:
    state = load()
    now = _now()
    state.last_tick_at = now
    state.tick_seconds = tick_seconds
    nxt = datetime.now() + timedelta(seconds=tick_seconds)
    state.next_tick_at = nxt.strftime(_TS_FMT)
    save(state)
    return state


def set_mom_report(text: str) -> BoardState:
    state = load()
    state.last_mom_report = text.strip()[:4000] if text else None
    state.last_mom_report_at = _now() if text else None
    save(state)
    return state
