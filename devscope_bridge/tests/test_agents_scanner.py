"""Tests for .claude/agents scanner."""

from pathlib import Path

from devscope_bridge import agents_scanner


def test_scan_agents_uses_default_project_root(tmp_path: Path, monkeypatch):
    agents_dir = tmp_path / ".claude" / "agents"
    agents_dir.mkdir(parents=True)
    (agents_dir / "default-agent.md").write_text(
        "---\nname: default-agent\ndescription: Default project agent.\n---\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(agents_scanner.session_store, "DEFAULT_CWD", str(tmp_path))
    agents = agents_scanner.scan_agents()
    assert [agent["name"] for agent in agents] == ["default-agent"]


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
