"""Tests for cursor_workspace helper."""

from pathlib import Path

from devscope_bridge.cursor_workspace import find_devscope_workspace


def test_find_devscope_workspace_from_repo_root():
    root = Path(__file__).resolve().parents[2]
    found = find_devscope_workspace(str(root))
    assert found is not None
    assert (Path(found) / ".cursor" / "mcp.json").is_file()


def test_find_devscope_workspace_from_subdir():
    sub = Path(__file__).resolve().parent
    found = find_devscope_workspace(str(sub))
    assert found is not None
