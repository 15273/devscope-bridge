"""Tests for orchestrator config persistence and quota throttle."""
import json

import pytest

from devscope_bridge import orchestrator_config as oc
from devscope_bridge import orchestrator_throttle as ot


def test_load_defaults_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(oc, "CONFIG_PATH", tmp_path / "orchestrator_config.json")
    s = oc.load()
    assert s.tick_seconds >= 30
    assert s.max_workers >= 1


def test_save_and_reload(tmp_path, monkeypatch):
    path = tmp_path / "orchestrator_config.json"
    monkeypatch.setattr(oc, "CONFIG_PATH", path)
    saved = oc.save(oc.OrchestratorSettings(tick_seconds=120, max_workers=2, paused=True))
    assert saved.tick_seconds == 120
    assert saved.max_workers == 2
    assert saved.paused is True
    reloaded = oc.load()
    assert reloaded.tick_seconds == 120
    assert json.loads(path.read_text())["max_workers"] == 2
    assert reloaded.paused is True


def test_clamp_bounds():
    s = oc.OrchestratorSettings(tick_seconds=10, max_workers=99).clamp()
    assert s.tick_seconds == 30
    assert s.max_workers == 16


@pytest.mark.asyncio
async def test_throttle_disabled(monkeypatch):
    settings = oc.OrchestratorSettings(max_workers=4, quota_throttle_enabled=False)
    effective, info = await ot.effective_max_workers(settings)
    assert effective == 4
    assert info["reason"] == "throttle_disabled"


@pytest.mark.asyncio
async def test_throttle_high_util(monkeypatch):
    async def fake_usage():
        return {"available": True, "limits": {"five_hour": {"utilization": 85}}}

    monkeypatch.setattr(ot.oauth_usage_service, "get_usage", fake_usage)
    settings = oc.OrchestratorSettings(max_workers=4, quota_high_utilization=80)
    effective, info = await ot.effective_max_workers(settings)
    assert effective == 1
    assert info["reason"] == "high_utilization"
