"""Tests for .claude/agents scanner."""

from pathlib import Path

from devscope_bridge import agents_scanner


def test_scan_agents_finds_project_agents():
    agents = agents_scanner.scan_agents()
    names = {a["name"] for a in agents}
    assert "ht-backend-engineer" in names
    assert all(a.get("description") for a in agents)


def test_scan_agents_custom_dir(tmp_path: Path):
    agents_dir = tmp_path / ".claude" / "agents"
    agents_dir.mkdir(parents=True)
    (agents_dir / "demo-agent.md").write_text(
        "---\nname: demo-agent\ndescription: Does demo things.\nmodel: sonnet\n---\n# Demo\n",
        encoding="utf-8",
    )
    found = agents_scanner.scan_agents(tmp_path)
    assert len(found) == 1
    assert found[0]["name"] == "demo-agent"
    assert found[0]["model"] == "sonnet"
