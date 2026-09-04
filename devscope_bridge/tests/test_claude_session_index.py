"""Discover / import Claude sessions from fixture trees — never the real home dirs."""

from __future__ import annotations

import json
from pathlib import Path

from devscope_bridge.claude_session_index import (
    SOURCE_CLAUDE_CODE,
    SOURCE_DESKTOP_CODE,
    SOURCE_DESKTOP_LOCAL,
    allocate_import_name,
    discover_sessions,
    import_slug,
    lookup_session,
)


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))


def _cli_tree(tmp_path: Path) -> Path:
    home = tmp_path / "claude"
    proj = home / "projects" / "-Users-demo-my-app"
    sid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    _write_jsonl(
        proj / f"{sid}.jsonl",
        [
            {
                "type": "user",
                "cwd": str(tmp_path / "my-app"),
                "timestamp": "2026-08-20T10:00:00+00:00",
                "message": {"role": "user", "content": "fix the login button"},
            },
            {
                "type": "custom-title",
                "customTitle": "Login button",
                "sessionId": sid,
            },
        ],
    )
    (tmp_path / "my-app").mkdir()
    # subagent must be ignored
    _write_jsonl(
        proj / sid / "subagents" / "agent-zzzz.jsonl",
        [{"type": "user", "message": {"role": "user", "content": "secret subagent"}}],
    )
    return home


def _desktop_code_tree(tmp_path: Path, cli_home: Path) -> Path:
    root = tmp_path / "claude-code-sessions"
    sidecar_dir = root / "acct" / "org"
    sidecar_dir.mkdir(parents=True)
    sid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    (sidecar_dir / "local_code-1.json").write_text(
        json.dumps(
            {
                "sessionId": "local_code-1",
                "cliSessionId": sid,
                "title": "Desktop Code title",
                "cwd": str(tmp_path / "my-app"),
                "originCwd": str(tmp_path / "my-app"),
                "lastActivityAt": 1_777_000_000_000,
                "isArchived": False,
            }
        )
    )
    assert (cli_home / "projects").is_dir()
    return root


def _desktop_local_tree(tmp_path: Path) -> Path:
    root = tmp_path / "local-agent-mode-sessions"
    org = root / "acct" / "org"
    sid = "bbbbbbbb-bbbb-cccc-dddd-ffffffffffff"
    sandbox = org / "local_abc"
    isolated = sandbox / ".claude" / "projects" / "-sandbox-out"
    _write_jsonl(
        isolated / f"{sid}.jsonl",
        [
            {
                "type": "user",
                "cwd": str(sandbox / "outputs"),
                "timestamp": "2026-08-21T12:00:00+00:00",
                "message": {"role": "user", "content": "publish the blog"},
            }
        ],
    )
    (sandbox / "outputs").mkdir(parents=True)
    org.mkdir(parents=True, exist_ok=True)
    (org / "local_abc.json").write_text(
        json.dumps(
            {
                "sessionId": "local_abc",
                "cliSessionId": sid,
                "title": "Xai blog publisher",
                "cwd": str(sandbox / "outputs"),
                "originCwd": str(tmp_path / "real-repo"),
                "lastActivityAt": 1_788_000_000_000,
                "isArchived": False,
            }
        )
    )
    (tmp_path / "real-repo").mkdir()
    archived = org / "local_old.json"
    archived.write_text(
        json.dumps(
            {
                "sessionId": "local_old",
                "cliSessionId": "cccccccc-bbbb-cccc-dddd-ffffffffffff",
                "title": "archived",
                "isArchived": True,
                "lastActivityAt": 1_799_000_000_000,
            }
        )
    )
    return root


def test_discover_skips_subagents_and_reads_cwd_from_jsonl(tmp_path):
    home = _cli_tree(tmp_path)
    items = discover_sessions(
        claude_home=home,
        desktop_code_root=tmp_path / "missing-code",
        desktop_local_root=tmp_path / "missing-local",
        owner_lookup=lambda _sid: None,
    )
    assert len(items) == 1
    item = items[0]
    assert item.session_id == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    assert item.title == "Login button"
    assert item.cwd == str(tmp_path / "my-app")
    assert item.source == SOURCE_CLAUDE_CODE
    assert item.can_resume is True
    assert all("subagent" not in (i.title or "") for i in items)


def test_desktop_code_sidecar_title_wins(tmp_path):
    home = _cli_tree(tmp_path)
    code_root = _desktop_code_tree(tmp_path, home)
    items = discover_sessions(
        claude_home=home,
        desktop_code_root=code_root,
        desktop_local_root=tmp_path / "missing-local",
        owner_lookup=lambda _sid: None,
    )
    assert len(items) == 1
    assert items[0].source == SOURCE_DESKTOP_CODE
    assert items[0].title == "Desktop Code title"
    assert items[0].can_resume is True


def test_desktop_local_sidecar_and_isolated_jsonl(tmp_path):
    local_root = _desktop_local_tree(tmp_path)
    items = discover_sessions(
        claude_home=tmp_path / "empty-claude",
        desktop_code_root=tmp_path / "missing-code",
        desktop_local_root=local_root,
        owner_lookup=lambda _sid: None,
    )
    assert len(items) == 1
    item = items[0]
    assert item.source == SOURCE_DESKTOP_LOCAL
    assert item.title == "Xai blog publisher"
    assert item.session_id == "bbbbbbbb-bbbb-cccc-dddd-ffffffffffff"
    assert item.config_dir and item.config_dir.endswith("/.claude")
    assert item.can_resume is True
    assert item.cwd == str(tmp_path / "real-repo")


def test_already_imported_marked(tmp_path):
    home = _cli_tree(tmp_path)
    sid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    items = discover_sessions(
        claude_home=home,
        desktop_code_root=tmp_path / "x",
        desktop_local_root=tmp_path / "y",
        owner_lookup=lambda s: "cc-aaaaaaaa" if s == sid else None,
    )
    assert items[0].already_imported is True
    assert items[0].bridge_name == "cc-aaaaaaaa"


def test_lookup_and_slug(tmp_path):
    home = _cli_tree(tmp_path)
    found = lookup_session(
        "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        SOURCE_CLAUDE_CODE,
        claude_home=home,
        desktop_code_root=tmp_path / "x",
        desktop_local_root=tmp_path / "y",
        owner_lookup=lambda _s: None,
    )
    assert found is not None
    assert import_slug(SOURCE_CLAUDE_CODE, found.session_id) == "cc-aaaaaaaa"
    assert allocate_import_name(SOURCE_CLAUDE_CODE, found.session_id, {"cc-aaaaaaaa"}) == "cc-aaaaaaaa-2"


def test_import_persists_session_id(tmp_path, monkeypatch):
    import devscope_bridge.session_store as store

    monkeypatch.setattr(store, "SESSIONS_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(store, "BRIDGE_DIR", tmp_path)
    monkeypatch.setattr(store, "DEFAULT_CWD", str(tmp_path))

    missing_cwd = str(tmp_path / "does-not-exist")
    entry = store.import_claude_session(
        session_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        source=SOURCE_CLAUDE_CODE,
        cwd=missing_cwd,
        display_title="Login button",
        claude_config_dir=None,
    )
    assert entry["session_id"] == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    assert entry["origin"] == SOURCE_CLAUDE_CODE
    assert entry["display_title"] == "Login button"
    assert entry["cwd"] == str(tmp_path)
    assert entry["name"] == "cc-aaaaaaaa"

    again = store.import_claude_session(
        session_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        source=SOURCE_CLAUDE_CODE,
        cwd=str(tmp_path),
        display_title="Login button",
    )
    assert again["name"] == "cc-aaaaaaaa"
    assert store.session_id_owner("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee") == "cc-aaaaaaaa"
