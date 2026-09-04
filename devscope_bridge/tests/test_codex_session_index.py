"""Codex discover/import from fixture trees — never ~/.codex."""

from __future__ import annotations

import json
from pathlib import Path

from devscope_bridge.codex_session_index import (
    allocate_import_name,
    discover_sessions,
    import_slug,
    lookup_session,
    read_models_cache,
)


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))


def _home(tmp_path: Path) -> Path:
    home = tmp_path / "codex"
    sid = "01a06712-3877-70b2-974c-c43c5265f746"
    _write_jsonl(
        home / "session_index.jsonl",
        [
            {
                "id": sid,
                "thread_name": "ATS pipeline",
                "updated_at": "2026-09-03T12:00:00+00:00",
                "cwd": str(tmp_path / "repo"),
            }
        ],
    )
    rollout = (
        home
        / "sessions"
        / "2026"
        / "09"
        / "03"
        / f"rollout-2026-09-03T14-40-43-{sid}.jsonl"
    )
    _write_jsonl(
        rollout,
        [
            {
                "type": "session_meta",
                "timestamp": "2026-09-03T14:40:43+00:00",
                "payload": {"id": sid, "cwd": str(tmp_path / "repo")},
            },
            {
                "type": "event_msg",
                "payload": {"type": "UserMessage", "text": "build the importer"},
            },
        ],
    )
    (tmp_path / "repo").mkdir()
    (home / "auth.json").write_text('{"access_token":"SECRET"}')
    (home / "models_cache.json").write_text(
        json.dumps({"models": [{"id": "gpt-5.6-sol", "display_name": "Sol"}, {"id": "hidden", "hidden": True}]})
    )
    return home


def test_discover_uses_index_title_and_cwd(tmp_path):
    home = _home(tmp_path)
    items = discover_sessions(codex_home=home, owner_lookup=lambda _sid: None)
    assert len(items) == 1
    assert items[0].title == "ATS pipeline"
    assert items[0].cwd == str(tmp_path / "repo")
    assert items[0].can_resume is True
    assert items[0].source == "codex"


def test_lookup_and_slug(tmp_path):
    home = _home(tmp_path)
    sid = "01a06712-3877-70b2-974c-c43c5265f746"
    found = lookup_session(sid, codex_home=home, owner_lookup=lambda _s: None)
    assert found is not None
    assert import_slug(sid) == "cx-01a06712"
    assert allocate_import_name(sid, set()) == "cx-01a06712"
    assert allocate_import_name(sid, {"cx-01a06712"}) == "cx-01a06712-2"


def test_models_cache_skips_hidden(tmp_path):
    home = _home(tmp_path)
    models = read_models_cache(home)
    assert models == [{"id": "gpt-5.6-sol", "label": "Sol"}]


def test_does_not_need_auth_json(tmp_path):
    home = _home(tmp_path)
    # Discover must work even if we refuse to read auth.json (we never open it).
    items = discover_sessions(codex_home=home, owner_lookup=lambda _sid: None)
    assert items[0].session_id.endswith("c43c5265f746")
