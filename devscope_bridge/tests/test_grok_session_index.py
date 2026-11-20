import json
from pathlib import Path

from devscope_bridge.grok_session_index import (
    SOURCE_GROK,
    allocate_import_name,
    discover_sessions,
    import_slug,
    lookup_session,
)


def _session_tree(tmp_path: Path) -> Path:
    home = tmp_path / "grok"
    group = home / "sessions" / "%2FUsers%2Fdemo%2Fapp"
    sid = "01aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    sess = group / sid
    sess.mkdir(parents=True)
    (sess / "summary.json").write_text(
        json.dumps(
            {
                "info": {"id": sid, "cwd": str(tmp_path / "app")},
                "generated_title": "Fix the login",
                "session_summary": "Fix the login",
                "updated_at": "2026-09-10T12:00:00Z",
                "last_active_at": "2026-09-10T12:00:00Z",
            }
        )
    )
    (tmp_path / "app").mkdir()
    (group / "prompt_history.jsonl").write_text("{}\n")
    return home


def test_discover_reads_summary(tmp_path):
    home = _session_tree(tmp_path)
    items = discover_sessions(grok_home=home, owner_lookup=lambda _s: None)
    assert len(items) == 1
    item = items[0]
    assert item.session_id.startswith("01aaaa")
    assert item.title == "Fix the login"
    assert item.cwd == str(tmp_path / "app")
    assert item.source == SOURCE_GROK
    assert item.can_resume is True


def test_lookup_and_slug(tmp_path):
    home = _session_tree(tmp_path)
    sid = "01aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    found = lookup_session(sid, grok_home=home, owner_lookup=lambda _s: None)
    assert found is not None
    assert import_slug(sid) == "gk-01aaaaaa"
    assert allocate_import_name(sid, {"gk-01aaaaaa"}) == "gk-01aaaaaa-2"
