# devscope_bridge/tests/test_cursor_automation_hygiene.py
"""Cursor automation sessions must not --resume or inject recovery preamble."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from devscope_bridge import session_hygiene, session_manager, session_store


@pytest.mark.asyncio
async def test_cursor_worker_skips_resume(monkeypatch):
    captured: dict = {}

    async def fake_dispatch(name, prompt, prior_session_id, cwd, *, mode=None, model=None):
        captured["prior_session_id"] = prior_session_id
        captured["prompt"] = prompt
        q = asyncio.Queue()
        await q.put(MagicMock())
        return q

    monkeypatch.setattr(
        session_manager.session_manager_cursor,
        "dispatch_cursor",
        fake_dispatch,
    )
    monkeypatch.setattr(session_manager, "_session_agent", lambda _n: "cursor")
    monkeypatch.setattr(session_manager, "_session_cwd", lambda _n: "/tmp")
    monkeypatch.setattr(session_manager, "_session_mode", lambda _n: "act")
    monkeypatch.setattr(session_manager, "_session_model", lambda _n: None)
    monkeypatch.setattr(session_manager, "_session_claude_agent", lambda _n: None)
    monkeypatch.setattr(session_manager, "build_context_preamble", lambda _c: "")
    monkeypatch.setattr(session_manager, "extract_image_blocks", lambda _c: [])
    monkeypatch.setattr(
        session_store,
        "get_session",
        lambda _n: {"session_id": "old-chat-id", "agent": "cursor", "purpose": "worker"},
    )
    monkeypatch.setattr(session_store, "append_bridge_turn", lambda *a, **k: None)

    digest = "Orchestrator worker task digest " * 20
    await session_manager.run_prompt("worker-abc123", digest, mode="act")

    assert captured["prior_session_id"] is None
    assert "[Bridge context recovery]" not in captured["prompt"]


def test_session_purpose_heuristics():
    assert session_hygiene.session_purpose("mom") == "orchestrator"
    assert session_hygiene.session_purpose("mgr-dev") == "manager"
    assert session_hygiene.session_purpose("worker-x") == "worker"
    assert session_hygiene.is_automation_session("worker-x") is True
    assert session_hygiene.is_automation_session("my-chat") is False
