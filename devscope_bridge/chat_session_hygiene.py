"""
chat_session_hygiene.py — Auto-compact long user chat sessions + model coaching hints.

Runs after each Claude turn completes (session_reader result event). Automation
sessions (mom, mgr-*, worker-*) are excluded — see session_hygiene.py for those.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from devscope_bridge import compact_service, session_hygiene, session_reader, session_store
from devscope_bridge.models import SessionCoach, SlashCommandCard

logger = logging.getLogger(__name__)

_OPUS_PREFIX = "claude-opus"
_SONNET_SUGGEST = "claude-sonnet-4-6"
_HEAVY_AGENTS = frozenset({"ht-orchestrator"})

_last_auto_compact_at: dict[str, float] = {}
_AUTO_COMPACT_COOLDOWN_S = 900.0  # 15 min — avoid compact loops on cache-heavy sessions


@dataclass(frozen=True)
class ChatHygieneSettings:
    enabled: bool = True
    auto_compact_turns: int = 28
    auto_compact_total_tokens: int = 800_000
    auto_compact_context_tokens: int = 140_000
    warn_turns: int = 8
    warn_total_tokens: int = 120_000
    warn_context_tokens: int = 60_000
    suggest_sonnet_on_opus: bool = True


def load_settings() -> ChatHygieneSettings:
    from devscope_bridge.orchestrator_config import load

    s = load()
    return ChatHygieneSettings(
        enabled=bool(getattr(s, "chat_auto_compact_enabled", True)),
        auto_compact_turns=int(getattr(s, "chat_auto_compact_turns", 28)),
        auto_compact_total_tokens=int(getattr(s, "chat_auto_compact_total_tokens", 800_000)),
        auto_compact_context_tokens=int(getattr(s, "chat_auto_compact_context_tokens", 140_000)),
        warn_turns=int(getattr(s, "chat_warn_turns", 8)),
        warn_total_tokens=int(getattr(s, "chat_warn_total_tokens", 120_000)),
        warn_context_tokens=int(getattr(s, "chat_warn_context_tokens", 60_000)),
        suggest_sonnet_on_opus=bool(getattr(s, "chat_suggest_sonnet_on_opus", True)),
    )


def _usage_billable(usage: dict) -> int:
    """Tokens that reflect real burn — exclude cache re-reads from compact triggers."""
    return (
        int(usage.get("input_tokens") or 0)
        + int(usage.get("output_tokens") or 0)
        + int(usage.get("cache_write_tokens") or 0)
    )


def _usage_total(usage: dict) -> int:
    return _usage_billable(usage) + int(usage.get("cache_read_tokens") or 0)


def _is_opus(model: str | None) -> bool:
    return bool(model and model.lower().startswith(_OPUS_PREFIX))


def _should_auto_compact(usage: dict, last_context_tokens: int, cfg: ChatHygieneSettings) -> str | None:
    turns = int(usage.get("turn_count") or 0)
    billable = _usage_billable(usage)
    if turns >= cfg.auto_compact_turns:
        return f"{turns} turns in this CLI session"
    if billable >= cfg.auto_compact_total_tokens:
        return f"{billable:,} billable tokens (excludes cache re-reads)"
    if last_context_tokens >= cfg.auto_compact_context_tokens:
        return f"context window ~{last_context_tokens:,} tokens on last turn"
    return None


def _should_warn(
    session_name: str,
    usage: dict,
    last_context_tokens: int,
    entry: dict,
    cfg: ChatHygieneSettings,
) -> SessionCoach | None:
    turns = int(usage.get("turn_count") or 0)
    total = _usage_total(usage)
    model = (entry.get("model") or "") or None
    agent_slug = (entry.get("claude_agent") or "") or None
    cost = float(usage.get("cost_usd") or 0)

    reasons: list[str] = []
    if turns >= cfg.warn_turns:
        reasons.append(f"{turns} turns — each reply re-reads growing cache")
    if total >= cfg.warn_total_tokens:
        reasons.append(f"{total:,} tokens burned this session (${cost:.2f})")
    if last_context_tokens >= cfg.warn_context_tokens:
        reasons.append(f"~{last_context_tokens:,} tokens in context now")

    suggest_model: str | None = None
    if cfg.suggest_sonnet_on_opus and _is_opus(model):
        suggest_model = _SONNET_SUGGEST
        reasons.append("Opus is costly on long threads — Sonnet is enough for most review work")
    if agent_slug and agent_slug.lower() in _HEAVY_AGENTS:
        reasons.append(f"Subagent `{agent_slug}` adds orchestration overhead on every message")

    if not reasons:
        return None

    body = " · ".join(reasons)
    if suggest_model:
        body += f". Try `{suggest_model}` or /compact."

    return SessionCoach(
        session=session_name,
        level="warn",
        title="Session getting expensive",
        body=body,
        suggested_model=suggest_model,
        current_model=model,
        auto_action="none",
        metrics={
            "turn_count": turns,
            "total_tokens": total,
            "context_tokens": last_context_tokens,
            "cost_usd": round(cost, 4),
        },
    )


async def _emit_auto_compact_report(session_name: str, reason: str, result, model: str | None) -> SessionCoach:
    return SessionCoach(
        session=session_name,
        level="action",
        title="Fresh context started",
        body=f"Auto-compact fired: {reason}.",
        suggested_model=_SONNET_SUGGEST if _is_opus(model) else None,
        current_model=model,
        auto_action="compact",
        metrics={"reason": reason},
    )


def _is_mid_work(session_name: str) -> bool:
    """True while the session has a running turn, in-flight sub-agents, or a
    pending permission/ask-user decision.

    A turn that ended on tool_blocked/ask_user LOOKS idle (turn_done set) but
    is mid-work: compacting kills the process, and the user's decision then
    lands on "no active session" — the work is silently lost.

    Lazy imports avoid the session_manager ↔ session_reader ↔ this-module cycle.
    """
    from devscope_bridge import session_manager, session_reader, sub_agent_tracker

    return (
        session_manager.is_turn_running(session_name)
        or sub_agent_tracker.has_in_flight(session_name)
        or bool(session_reader.get_pending_permissions(session_name))
    )


async def _run_auto_compact(session_name: str, reason: str, q) -> None:
    """Auto-compact a long session — serialized with /compact via compact_service.

    A7: uses the SAME per-session lock as POST /compact and the /compact slash
    command (compact_service.guarded_compact) so a second concurrent compact
    no-ops instead of racing, and a summarizer failure aborts without wiping
    the session (RC-5/RC-6).

    Never fires mid-work: apply_compact_reset kills the CLI process, which
    would abort a running turn and any in-flight sub-agents. Deferring here
    (no cooldown stamp) lets the next turn-end tick retry. Manual /compact
    (builtin command path) is unaffected.
    """
    if _is_mid_work(session_name):
        logger.info(
            "chat hygiene: auto-compact deferred for '%s' — turn running / sub-agents in flight",
            session_name,
        )
        return
    entry = session_store.get_session(session_name)
    if entry is None or entry.get("agent", "claude") != "claude":
        return
    if not entry.get("session_id"):
        return
    _last_auto_compact_at[session_name] = time.monotonic()

    await q.put(SlashCommandCard(
        session=session_name,
        kind="compact",
        title="Auto-compacting…",
        body=f"Long session ({reason}). Summarizing and starting a fresh CLI context.",
        data={"status": "in_progress", "auto": True},
    ))

    result = await compact_service.guarded_compact(session_name, "", q)
    if not result.ok:
        logger.info(
            "chat hygiene: auto-compact skipped for '%s' (%s)", session_name, result.skipped,
        )
        return
    await compact_service.apply_compact_reset(session_name, result.preamble, result.was_real_summary)

    await q.put(SlashCommandCard(
        session=session_name,
        kind="compact",
        title="Auto-compacted" if result.was_real_summary else "Auto-compacted (fallback)",
        body=(
            "Claude CLI restarted with the summary only. "
            "Panel history stays visible for you — it is not sent again."
            if result.was_real_summary
            else "Brief recovery note saved — consider /new if burn continues."
        ),
        data={"was_real_summary": result.was_real_summary, "auto": True, "reason": reason},
    ))

    coach = await _emit_auto_compact_report(session_name, reason, result, entry.get("model"))
    await q.put(coach)
    logger.info("chat hygiene: auto-compact %s (%s)", session_name, reason)


async def evaluate_after_turn(session_name: str, q, last_context_tokens: int) -> None:
    """Post-turn hook: auto-compact or emit coaching hint for user chat sessions."""
    if session_hygiene.is_automation_session(session_name):
        return
    entry = session_store.get_session(session_name)
    if entry is None or entry.get("agent", "claude") != "claude":
        return

    cfg = load_settings()
    if not cfg.enabled:
        return

    usage = session_reader.get_session_usage(session_name)
    entry = {**entry, "name": session_name}

    compact_reason = _should_auto_compact(usage, last_context_tokens, cfg)
    if compact_reason:
        now = time.monotonic()
        last = _last_auto_compact_at.get(session_name, 0.0)
        if now - last < _AUTO_COMPACT_COOLDOWN_S:
            logger.debug(
                "chat hygiene: skip auto-compact %s — cooldown (%.0fs left)",
                session_name,
                _AUTO_COMPACT_COOLDOWN_S - (now - last),
            )
        else:
            # Cooldown is stamped inside _run_auto_compact AFTER its mid-work
            # guard — a deferred attempt must retry on the next turn-end tick.
            asyncio.create_task(_run_auto_compact(session_name, compact_reason, q))
        return

    coach = _should_warn(session_name, usage, last_context_tokens, entry, cfg)
    if coach:
        await q.put(coach)
