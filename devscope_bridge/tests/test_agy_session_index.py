from __future__ import annotations

from pathlib import Path

from devscope_bridge.agy_session_index import discover_sessions, import_slug, lookup_session


def _cli(tmp_path: Path) -> Path:
    root = tmp_path / "antigravity-cli"
    (root / "conversations").mkdir(parents=True)
    (root / "history.jsonl").write_text(
        '{"conversationId":"aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",'
        '"display":"CLI research","workspace":"%s","timestamp":"2026-09-01T10:00:00Z"}\n'
        % (tmp_path / "ws")
    )
    return root


def _ide(tmp_path: Path) -> Path:
    root = tmp_path / "antigravity"
    sid = "ffffffff-1111-2222-3333-444444444444"
    (root / "conversations").mkdir(parents=True)
    (root / "conversations" / f"{sid}.pb").write_bytes(b"not-a-real-protobuf")
    brain = root / "brain" / sid
    brain.mkdir(parents=True)
    (brain / "task.md").write_text("# Hire pipeline\nDo the thing\n")
    (brain / "walkthrough.md").write_text("We finished step 1.")
    return root


def test_discover_splits_cli_and_ide(tmp_path):
    items = discover_sessions(
        cli_root=_cli(tmp_path),
        ide_root=_ide(tmp_path),
        owner_lookup=lambda _s: None,
    )
    sources = {i.source: i for i in items}
    assert "antigravity_cli" in sources
    assert sources["antigravity_cli"].can_resume is True
    assert sources["antigravity_cli"].title == "CLI research"
    assert "antigravity_ide" in sources
    assert sources["antigravity_ide"].can_resume is False
    assert sources["antigravity_ide"].title == "Hire pipeline"
    assert sources["antigravity_ide"].seed_summary
    assert "Hire pipeline" in (sources["antigravity_ide"].seed_summary or "")


def test_lookup_and_slugs(tmp_path):
    cli = _cli(tmp_path)
    found = lookup_session(
        "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        "antigravity_cli",
        cli_root=cli,
        ide_root=tmp_path / "no-ide",
        owner_lookup=lambda _s: None,
    )
    assert found is not None
    assert import_slug("antigravity_cli", found.session_id) == "ag-aaaaaaaa"
    assert import_slug("antigravity_ide", "ffffffff-1111-2222-3333-444444444444") == "ai-ffffffff"
