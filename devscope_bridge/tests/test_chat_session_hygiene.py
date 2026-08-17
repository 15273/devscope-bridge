# devscope_bridge/tests/test_chat_session_hygiene.py
"""Tests for user-chat auto-compact and coaching hints."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from devscope_bridge import chat_session_hygiene, session_reader, session_store
from devscope_bridge.chat_session_hygiene import ChatHygieneSettings


@pytest.fixture
def chat_env(tmp_path, monkeypatch):
    sessions_path = tmp_path / "sessions.json"
    sessions_path.write_text("{}")
    monkeypatch.setattr(session_store, "SESSIONS_FILE", sessions_path)
    monkeypatch.setattr(session_store, "BRIDGE_DIR", tmp_path)
    session_reader.reset_session_usage("my-chat")
    chat_session_hygiene._last_auto_compact_at.clear()
    return tmp_path


def test_should_auto_compact_on_turns():
    cfg = ChatHygieneSettings(auto_compact_turns=10)
    usage = {"turn_count": 10, "input_tokens": 1, "output_tokens": 1, "cache_read_tokens": 0, "cache_write_tokens": 0}
    reason = chat_session_hygiene._should_auto_compact(usage, 1000, cfg)
    assert reason is not None
    assert "10 turns" in reason


def test_should_auto_compact_on_context():
    cfg = ChatHygieneSettings(auto_compact_context_tokens=50_000)
    usage = {"turn_count": 2, "input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cache_write_tokens": 0}
    reason = chat_session_hygiene._should_auto_compact(usage, 80_000, cfg)
    assert reason is not None


def test_cache_read_alone_does_not_trigger_token_compact():
    cfg = ChatHygieneSettings(auto_compact_total_tokens=100_000, auto_compact_turns=999)
    usage = {
        "turn_count": 5,
        "input_tokens": 1_000,
        "output_tokens": 1_000,
        "cache_read_tokens": 900_000,
        "cache_write_tokens": 0,
    }
    reason = chat_session_hygiene._should_auto_compact(usage, 10_000, cfg)
    assert reason is None


def test_warn_suggests_sonnet_for_opus(chat_env):
    cfg = ChatHygieneSettings(warn_turns=5, suggest_sonnet_on_opus=True)
    usage = {"turn_count": 9, "input_tokens": 1, "output_tokens": 1, "cache_read_tokens": 200_000, "cache_write_tokens": 0, "cost_usd": 1.5}
    entry = {"model": "claude-opus-4-8", "claude_agent": None}
    coach = chat_session_hygiene._should_warn("my-chat", usage, 70_000, entry, cfg)
    assert coach is not None
    assert coach.suggested_model == "claude-sonnet-4-6"
    assert "Opus" in coach.body


@pytest.mark.asyncio
async def test_evaluate_skips_automation(chat_env, monkeypatch):
    monkeypatch.setattr(chat_session_hygiene.session_hygiene, "is_automation_session", lambda _n: True)
    q = asyncio.Queue()
    await chat_session_hygiene.evaluate_after_turn("mom", q, 1000)
    assert q.empty()


@pytest.mark.asyncio
async def test_evaluate_emits_coach_for_long_chat(chat_env, monkeypatch):
    monkeypatch.setattr(chat_session_hygiene.session_hygiene, "is_automation_session", lambda _n: False)
    monkeypatch.setattr(chat_session_hygiene, "load_settings", lambda: ChatHygieneSettings(
        auto_compact_turns=999,
        auto_compact_total_tokens=9_999_999,
        auto_compact_context_tokens=999_999,
        warn_turns=3,
        warn_total_tokens=10_000,
    ))
    session_store.upsert_session("my-chat", "sid-1", agent="claude", cwd="/tmp", model="claude-opus-4-8")
    session_reader.accumulate_usage("my-chat", {
        "usage": {"input_tokens": 50_000, "output_tokens": 500, "cache_read_input_tokens": 80_000, "cache_creation_input_tokens": 0},
        "total_cost_usd": 0.5,
    })
    for _ in range(3):
        session_reader.accumulate_usage("my-chat", {
            "usage": {"input_tokens": 1000, "output_tokens": 100, "cache_read_input_tokens": 5000, "cache_creation_input_tokens": 0},
            "total_cost_usd": 0.1,
        })

    q = asyncio.Queue()
    await chat_session_hygiene.evaluate_after_turn("my-chat", q, 50_000)
    assert not q.empty()
    frame = await q.get()
    assert frame.type == "session_coach"


# ─────────────────────────────────────────────
# FIX 1: auto-compact must never fire mid-work
# ─────────────────────────────────────────────

def _patch_mid_work(monkeypatch, *, turn_running: bool, sub_agents: bool):
    from devscope_bridge import session_manager, sub_agent_tracker
    monkeypatch.setattr(session_manager, "is_turn_running", lambda _n: turn_running)
    monkeypatch.setattr(sub_agent_tracker, "has_in_flight", lambda _n: sub_agents)


@pytest.mark.asyncio
async def test_auto_compact_deferred_while_turn_running(chat_env, monkeypatch):
    from devscope_bridge import compact_service
    session_store.upsert_session("my-chat", "sid-1", agent="claude", cwd="/tmp")
    _patch_mid_work(monkeypatch, turn_running=True, sub_agents=False)
    guarded = AsyncMock()
    monkeypatch.setattr(compact_service, "guarded_compact", guarded)

    q = asyncio.Queue()
    await chat_session_hygiene._run_auto_compact("my-chat", "test reason", q)

    guarded.assert_not_awaited()
    assert q.empty(), "deferred auto-compact must not emit any frames"
    assert "my-chat" not in chat_session_hygiene._last_auto_compact_at, \
        "deferral must NOT stamp the cooldown — next tick must retry"


@pytest.mark.asyncio
async def test_auto_compact_deferred_while_sub_agents_in_flight(chat_env, monkeypatch):
    from devscope_bridge import compact_service
    session_store.upsert_session("my-chat", "sid-1", agent="claude", cwd="/tmp")
    _patch_mid_work(monkeypatch, turn_running=False, sub_agents=True)
    guarded = AsyncMock()
    monkeypatch.setattr(compact_service, "guarded_compact", guarded)

    q = asyncio.Queue()
    await chat_session_hygiene._run_auto_compact("my-chat", "test reason", q)

    guarded.assert_not_awaited()
    assert q.empty()
    assert "my-chat" not in chat_session_hygiene._last_auto_compact_at


@pytest.mark.asyncio
async def test_auto_compact_proceeds_when_idle(chat_env, monkeypatch):
    from devscope_bridge import compact_service
    session_store.upsert_session("my-chat", "sid-1", agent="claude", cwd="/tmp")
    _patch_mid_work(monkeypatch, turn_running=False, sub_agents=False)
    result = MagicMock(ok=True, preamble="summary", was_real_summary=True, skipped=None)
    guarded = AsyncMock(return_value=result)
    apply_reset = AsyncMock()
    monkeypatch.setattr(compact_service, "guarded_compact", guarded)
    monkeypatch.setattr(compact_service, "apply_compact_reset", apply_reset)

    q = asyncio.Queue()
    await chat_session_hygiene._run_auto_compact("my-chat", "test reason", q)

    guarded.assert_awaited_once()
    apply_reset.assert_awaited_once_with("my-chat", "summary", True)
    assert "my-chat" in chat_session_hygiene._last_auto_compact_at
    assert not q.empty(), "successful auto-compact emits progress cards"
