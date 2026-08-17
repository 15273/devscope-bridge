# devscope_bridge/tests/test_capability_registry.py
"""Tests for the capability registry (static entries, probes, dynamic plugins)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from devscope_bridge import capability_registry as cr


@pytest.fixture(autouse=True)
def _reset_mcp_cache():
    cr._mcp_status_cache = None
    yield
    cr._mcp_status_cache = None


def test_static_capabilities_present():
    for cap_id in ("browser", "whatsapp", "gmail", "calendar", "notion",
                   "cursor_plugins", "codebase_scout", "parallel_ask"):
        assert cr.get_capability(cap_id) is not None


def test_plugin_capability_minted_on_the_fly():
    cap = cr.get_capability("plugin:linear")
    assert cap is not None
    assert cap.backends == ("cursor_agent",)
    assert "cursor_plugin:linear" in cap.requires
    assert cr.get_capability("no-such-capability") is None


@pytest.mark.asyncio
async def test_check_requires_maps_each_requirement():
    cap = cr.get_capability("notion")
    with patch.object(cr, "_resolve_cursor_bin", return_value="/usr/bin/cursor-agent"), \
         patch.object(cr, "_mcp_list_status", return_value={"Notion beta": "ready"}):
        result = await cr.check_requires(cap)
    assert result == {"cursor_agent_bin": True, "cursor_plugin:notion": True}


@pytest.mark.asyncio
async def test_serialize_unavailable_capability_exposes_missing_and_hint():
    with patch.object(cr, "_resolve_cursor_bin", return_value=None), \
         patch.object(cr, "_mcp_list_status", return_value={}):
        entries = await cr.list_capabilities()
    notion = next(e for e in entries if e["id"] == "notion")
    assert notion["available"] is False
    assert notion["active_backend"] is None
    assert "cursor_agent_bin" in notion["missing"]
    assert notion["setup_hint"]


@pytest.mark.asyncio
async def test_dynamic_plugins_skip_devscope_servers_and_notion():
    status = {
        "browser-control": "ready",   # DevScope's own server — skipped
        "Notion beta": "ready",       # covered by the static 'notion' entry
        "linear": "ready",            # genuine plugin — minted
        "asana": "loading",           # not ready — skipped
    }
    with patch.object(cr, "_mcp_list_status", return_value=status):
        plugins = await cr.dynamic_plugin_capabilities()
    assert [p.id for p in plugins] == ["plugin:linear"]


@pytest.mark.asyncio
async def test_cursor_mcp_status_is_ttl_cached():
    calls = {"n": 0}

    def fake_status():
        calls["n"] += 1
        return {"linear": "ready"}

    with patch.object(cr, "_mcp_list_status", new=fake_status):
        await cr.cursor_mcp_status()
        await cr.cursor_mcp_status()
    assert calls["n"] == 1
