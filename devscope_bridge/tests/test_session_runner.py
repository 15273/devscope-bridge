"""BridgeSessionRunner must honor the schedule's agent, including grok_bot."""

from __future__ import annotations

import asyncio

import pytest

import devscope_bridge.session_manager as mgr
import devscope_bridge.session_runner as runner_mod
import devscope_bridge.session_store as store


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "SESSIONS_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(store, "BRIDGE_DIR", tmp_path)
    mgr._sessions.clear()
    yield
    mgr._sessions.clear()


@pytest.mark.asyncio
async def test_run_turn_creates_grok_bot_session(tmp_path, monkeypatch):
    prompts: list[tuple] = []

    async def fake_run_prompt(name, prompt, mode=None):
        prompts.append((name, prompt, mode, store.get_session(name)["agent"]))
        return asyncio.Queue()

    async def fake_await(self, name, timeout_s):
        return True

    monkeypatch.setattr(mgr, "run_prompt", fake_run_prompt)
    monkeypatch.setattr(runner_mod.BridgeSessionRunner, "_await_turn", fake_await)

    runner = runner_mod.BridgeSessionRunner()
    ok = await runner.run_turn(
        "worker-1", "do the thing", agent="grok_bot", cwd=str(tmp_path),
    )
    assert ok is True
    assert store.get_session("worker-1")["agent"] == "grok_bot"
    assert prompts[0][3] == "grok_bot"


@pytest.mark.asyncio
async def test_run_turn_switches_existing_worker_to_grok_bot(tmp_path, monkeypatch):
    store.create_session_metadata("worker-1", "claude", str(tmp_path), purpose="worker")

    async def fake_run_prompt(name, prompt, mode=None):
        return asyncio.Queue()

    async def fake_await(self, name, timeout_s):
        return True

    monkeypatch.setattr(mgr, "run_prompt", fake_run_prompt)
    monkeypatch.setattr(runner_mod.BridgeSessionRunner, "_await_turn", fake_await)

    runner = runner_mod.BridgeSessionRunner()
    await runner.run_turn("worker-1", "hi", agent="grok_bot")
    assert store.get_session("worker-1")["agent"] == "grok_bot"
