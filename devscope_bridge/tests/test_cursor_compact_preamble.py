"""Compact preamble must reach Cursor after auto-compact (main.py must not pop early)."""

import asyncio

import pytest
from unittest.mock import patch

import devscope_bridge.builtin_commands as bc
import devscope_bridge.session_manager as mgr
import devscope_bridge.session_store as store


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "SESSIONS_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(store, "BRIDGE_DIR", tmp_path)
    monkeypatch.setattr(store, "BRIDGE_TRANSCRIPTS_DIR", tmp_path / "transcripts")
    bc.pending_compact_preambles.clear()


@pytest.mark.asyncio
async def test_cursor_run_prompt_injects_stashed_compact_preamble(monkeypatch):
    store.upsert_session("jobright", "chat-uuid", agent="cursor", cwd="/tmp")
    bc.pending_compact_preambles["jobright"] = (
        "[Bridge compact] Jobright in-page panel vs new-tab ATS was the topic."
    )

    captured: dict = {}

    async def fake_dispatch(name, prompt, prior, cwd, mode=None, model=None):
        captured["prompt"] = prompt
        q: asyncio.Queue = asyncio.Queue()
        await q.put(mgr.AiDone(session=name, exit_code=0))
        return q

    monkeypatch.setattr(mgr.session_manager_cursor, "dispatch_cursor", fake_dispatch)
    monkeypatch.setattr(mgr, "_session_agent", lambda n: "cursor")
    monkeypatch.setattr(mgr, "_session_cwd", lambda n: "/tmp")
    monkeypatch.setattr(mgr, "_session_mode", lambda n: None)
    monkeypatch.setattr(mgr, "_session_model", lambda n: None)
    monkeypatch.setattr(mgr, "build_context_preamble", lambda c: "")

    await mgr.run_prompt("jobright", "מה קורה?")

    assert "Jobright in-page panel" in captured["prompt"]
    assert "מה קורה?" in captured["prompt"]
    assert "jobright" not in bc.pending_compact_preambles


@pytest.mark.asyncio
async def test_cursor_short_message_skips_recovery_when_compact_present(monkeypatch):
    store.upsert_session("s", "chat-id", agent="cursor", cwd="/tmp")
    store.append_bridge_turn("s", "user", "only old context")
    bc.pending_compact_preambles["s"] = "[Bridge compact] Full summary here."

    captured: dict = {}

    async def fake_dispatch(name, prompt, prior, cwd, mode=None, model=None):
        captured["prompt"] = prompt
        q: asyncio.Queue = asyncio.Queue()
        await q.put(mgr.AiDone(session=name, exit_code=0))
        return q

    monkeypatch.setattr(mgr.session_manager_cursor, "dispatch_cursor", fake_dispatch)
    monkeypatch.setattr(mgr, "_session_agent", lambda n: "cursor")
    monkeypatch.setattr(mgr, "_session_cwd", lambda n: "/tmp")
    monkeypatch.setattr(mgr, "_session_mode", lambda n: None)
    monkeypatch.setattr(mgr, "_session_model", lambda n: None)
    monkeypatch.setattr(mgr, "build_context_preamble", lambda c: "")

    await mgr.run_prompt("s", "מה קורה?")

    assert "Full summary here" in captured["prompt"]
    assert "Bridge context recovery" not in captured["prompt"]
