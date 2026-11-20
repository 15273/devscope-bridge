"""Cloud Claude Code sessions: list parse, repo match, dirty-git refuse, teleport import."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from devscope_bridge.claude_cloud_sessions import (
    CloudTeleportError,
    parse_cloud_session_list,
    parse_cloud_session_ref,
    parse_git_owner_name,
    prepare_cloud_teleport,
    resolve_local_checkout,
    working_tree_dirty,
)


def test_parse_cloud_session_ref_accepts_id_and_url():
    assert parse_cloud_session_ref("session_01RyZ89nysBFFZnqFMZ4KpkZ") == (
        "session_01RyZ89nysBFFZnqFMZ4KpkZ"
    )
    assert parse_cloud_session_ref(
        "https://claude.ai/code/session_01ABC?from=cli&m=0"
    ) == "session_01ABC"
    assert parse_cloud_session_ref("claude.ai/code/cse_01xyz") == "cse_01xyz"
    assert parse_cloud_session_ref("not-a-session") is None
    assert parse_cloud_session_ref("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee") is None


def test_parse_cloud_session_list_skips_archived_and_reads_repo():
    items = parse_cloud_session_list(
        {
            "data": [
                {
                    "id": "session_01LIVE",
                    "title": "Fix auth",
                    "status": "ok",
                    "worker_status": "idle",
                    "created_at": "2026-09-01T10:00:00Z",
                    "last_event_at": "2026-09-02T11:00:00Z",
                    "config": {
                        "sources": [
                            {
                                "type": "git_repository",
                                "url": "https://github.com/Acme/App.git",
                            }
                        ]
                    },
                },
                {
                    "id": "session_01DEAD",
                    "title": "old",
                    "status": "archived",
                    "last_event_at": "2026-08-01T00:00:00Z",
                },
            ]
        },
        checkout_lookup=lambda _repo: None,
        owner_lookup=lambda _sid: None,
    )
    assert len(items) == 1
    item = items[0]
    assert item.session_id == "session_01LIVE"
    assert item.title == "Fix auth"
    assert item.source == "claude_cloud"
    assert item.last_used == "2026-09-02T11:00:00Z"
    assert item.can_resume is False
    assert item.cwd == "acme/app"


def test_parse_cloud_session_list_marks_checkout_and_imported(tmp_path):
    checkout = tmp_path / "App"
    checkout.mkdir()
    items = parse_cloud_session_list(
        {
            "data": [
                {
                    "id": "session_01LIVE",
                    "title": "Fix auth",
                    "config": {
                        "sources": [
                            {"type": "git_repository", "url": "git@github.com:acme/app.git"}
                        ]
                    },
                    "last_event_at": "2026-09-02T11:00:00Z",
                }
            ]
        },
        checkout_lookup=lambda repo: str(checkout) if repo == "acme/app" else None,
        owner_lookup=lambda sid: "cr-01live" if sid == "session_01LIVE" else None,
    )
    assert items[0].can_resume is True
    assert items[0].cwd == str(checkout)
    assert items[0].already_imported is True
    assert items[0].bridge_name == "cr-01live"


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://github.com/Acme/App.git", "acme/app"),
        ("git@github.com:Acme/App.git", "acme/app"),
        ("ssh://git@github.com/Acme/App", "acme/app"),
        ("https://github.com/Acme/App", "acme/app"),
        ("acme/app", "acme/app"),
        ("not a repo", None),
    ],
)
def test_parse_git_owner_name(url, expected):
    assert parse_git_owner_name(url) == expected


def _git_init(path: Path, remote: str) -> None:
    path.mkdir(parents=True)
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "remote", "add", "origin", remote], cwd=path, check=True, capture_output=True)


def test_resolve_local_checkout_matches_remote(tmp_path):
    repo = tmp_path / "app"
    _git_init(repo, "https://github.com/Acme/App.git")
    other = tmp_path / "other"
    _git_init(other, "https://github.com/Acme/Other.git")
    found = resolve_local_checkout("acme/app", [str(other), str(repo)])
    assert found == str(repo)
    assert resolve_local_checkout("nope/nope", [str(repo)]) is None


def test_working_tree_dirty_detects_untracked(tmp_path):
    repo = tmp_path / "app"
    _git_init(repo, "https://github.com/Acme/App.git")
    assert working_tree_dirty(str(repo)) is False
    (repo / "wip.txt").write_text("nope")
    assert working_tree_dirty(str(repo)) is True


def test_prepare_cloud_teleport_refuses_dirty_tree(tmp_path):
    repo = tmp_path / "app"
    _git_init(repo, "https://github.com/Acme/App.git")
    (repo / "wip.txt").write_text("nope")
    with pytest.raises(CloudTeleportError, match="uncommitted"):
        prepare_cloud_teleport(
            {
                "id": "session_01LIVE",
                "config": {
                    "sources": [
                        {"type": "git_repository", "url": "https://github.com/Acme/App.git"}
                    ]
                },
            },
            candidate_cwds=[str(repo)],
        )


def test_prepare_cloud_teleport_requires_matching_checkout(tmp_path):
    repo = tmp_path / "app"
    _git_init(repo, "https://github.com/Acme/Other.git")
    with pytest.raises(CloudTeleportError, match="No local checkout"):
        prepare_cloud_teleport(
            {
                "id": "session_01LIVE",
                "config": {
                    "sources": [
                        {"type": "git_repository", "url": "https://github.com/Acme/App.git"}
                    ]
                },
            },
            candidate_cwds=[str(repo)],
        )


def test_run_teleport_reads_session_id_from_init(tmp_path, monkeypatch):
    import io

    from devscope_bridge.claude_cloud_sessions import run_teleport

    class FakeProc:
        def __init__(self):
            self.stdin = io.StringIO()
            self.stdout = io.StringIO(
                '{"type":"system","subtype":"init","session_id":"local-uuid"}\n'
            )
            self.stderr = io.StringIO("")
            self._code = None

        def poll(self):
            return self._code

        def terminate(self):
            self._code = 0

        def kill(self):
            self._code = -9

        def wait(self, timeout=None):
            self._code = 0
            return 0

    monkeypatch.setattr(
        "devscope_bridge.claude_cloud_sessions.subprocess.Popen",
        lambda *a, **k: FakeProc(),
    )
    assert run_teleport("session_01LIVE", str(tmp_path)) == "local-uuid"


def test_prepare_cloud_teleport_returns_cwd_when_clean(tmp_path):
    repo = tmp_path / "app"
    _git_init(repo, "git@github.com:Acme/App.git")
    cwd, session_id = prepare_cloud_teleport(
        {
            "id": "session_01LIVE",
            "config": {
                "sources": [
                    {"type": "git_repository", "url": "https://github.com/Acme/App.git"}
                ]
            },
        },
        candidate_cwds=[str(repo)],
    )
    assert cwd == str(repo)
    assert session_id == "session_01LIVE"
