"""Tests for DevScope capabilities endpoint payload."""

from devscope_bridge.capabilities import build_capabilities, DEVSCOPE_MCP_SERVERS


def test_build_capabilities_includes_core_servers():
    caps = build_capabilities()
    ids = {s["id"] for s in caps["mcp_servers"]}
    assert "browser-control" in ids
    assert "whatsapp-control" in ids
    assert "gmail-control" in ids
    assert "calendar-control" in ids
    assert "meta-ads-control" in ids
    assert "task-control" in ids
    assert "linkedin-bot" not in ids
    assert "job-pipeline" not in ids


def test_build_capabilities_skills_list():
    caps = build_capabilities()
    skill_ids = {s["id"] for s in caps["skills"]}
    assert "devscope-browser" in skill_ids
    assert "devscope-capabilities" in skill_ids
    assert "comms-cockpit" in skill_ids
    assert "meta-ads-cockpit" in skill_ids


def test_mcp_server_metadata_complete():
    for sid, meta in DEVSCOPE_MCP_SERVERS.items():
        assert meta.get("label")
        assert meta.get("description")
        assert meta.get("skill")
