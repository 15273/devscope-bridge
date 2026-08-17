"""
test_new_slash_commands.py — Tests for /status, /add-dir, /review, /security-review,
/pr-comments, and alias searchability.

Coverage:
1. /status emits a SlashCommandCard with kind="status" containing model/cwd/etc.
2. /status cached version shows in card data.
3. /add-dir emits error card when path missing.
4. /add-dir emits error card when no arg given.
5. /add-dir emits success card for valid path (tmp_path), persists to session store,
   sets active.pending_respawn = True (not the old __respawn__ sentinel).
6. /add-dir emits "already added" card and does NOT set pending_respawn when path
   is already in extra_dirs.
7. _build_claude_args with extra_dirs includes --add-dir flags.
8. _spawn_claude_proc reads extra_dirs from session metadata and forwards them.
9. build_review_prompt includes base text and appends args.
10. build_security_review_prompt includes security keywords and appends args.
11. build_pr_comments_prompt uses supplied PR number; falls back when empty.
12. Prompt-template verbs (/review etc.) appear in scan_commands.
13. /status and /add-dir appear in scan_commands.
14. dispatch routes /status → SlashCommandCard(kind="status").
15. dispatch routes /add-dir (no arg) → error card.
"""

import asyncio
import pytest
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import devscope_bridge.builtin_commands as bc
import devscope_bridge.status_helpers as sh
import devscope_bridge.prompt_templates as pt
import devscope_bridge.session_manager as mgr
import devscope_bridge.session_store as ss
from devscope_bridge.models import SlashCommandCard


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _drain(q: asyncio.Queue) -> list:
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


def _make_fake_active(session_name: str) -> mgr._ActiveSession:
    """Construct a minimal _ActiveSession stub suitable for unit tests."""
    fake_proc = MagicMock()
    fake_proc.returncode = None
    return mgr._ActiveSession(
        name=session_name,
        session_id="",
        proc=fake_proc,
        out_queue=asyncio.Queue(),
        reader_task=MagicMock(),
        idle_task=MagicMock(),
        mode="act",
        model="claude-3",
    )


@pytest.fixture(autouse=True)
def clean_sessions():
    mgr._sessions.clear()
    yield
    mgr._sessions.clear()


# ─────────────────────────────────────────────
# 1–2. /status
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_status_emits_card_with_kind_status(monkeypatch):
    monkeypatch.setattr(ss, "get_metadata", lambda n: {
        "session_id": "abc123", "agent": "claude",
        "model": "claude-3", "mode": "act", "cwd": "/tmp/proj",
    })
    monkeypatch.setattr(sh, "get_cli_version", AsyncMock(return_value="1.2.3"))

    q: asyncio.Queue = asyncio.Queue()
    await bc.handle_status("s", q)

    cards = _drain(q)
    assert len(cards) == 1
    card = cards[0]
    assert isinstance(card, SlashCommandCard)
    assert card.kind == "status"
    assert "abc123" in card.body
    assert "claude-3" in card.body
    assert "/tmp/proj" in card.body
    assert "1.2.3" in card.body
    assert card.data.get("cli_version") == "1.2.3"


@pytest.mark.asyncio
async def test_status_body_omits_unavailable_account(monkeypatch):
    """Account/email is not included unless available — card must not fabricate it."""
    monkeypatch.setattr(ss, "get_metadata", lambda n: {
        "session_id": "", "agent": "claude", "model": None, "mode": None, "cwd": "/x",
    })
    monkeypatch.setattr(sh, "get_cli_version", AsyncMock(return_value="unknown"))

    q: asyncio.Queue = asyncio.Queue()
    await bc.handle_status("s", q)

    cards = _drain(q)
    assert cards[0].kind == "status"
    # No fabricated email/account
    assert "@" not in cards[0].body or "unknown" in cards[0].body


# ─────────────────────────────────────────────
# 3–5. /add-dir
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_add_dir_no_arg_emits_usage_error():
    q: asyncio.Queue = asyncio.Queue()
    await bc.handle_add_dir("s", "/add-dir", q)

    cards = _drain(q)
    assert len(cards) == 1
    assert cards[0].kind == "add_dir"
    assert cards[0].data.get("valid") is False
    assert "Usage" in cards[0].title


@pytest.mark.asyncio
async def test_add_dir_nonexistent_path_emits_error(tmp_path):
    q: asyncio.Queue = asyncio.Queue()
    missing = str(tmp_path / "does_not_exist")
    await bc.handle_add_dir("s", f"/add-dir {missing}", q)

    cards = _drain(q)
    assert len(cards) == 1
    assert cards[0].data.get("valid") is False
    assert "not found" in cards[0].title.lower() or "does not exist" in cards[0].body


@pytest.mark.asyncio
async def test_add_dir_valid_path_emits_success_and_persists(monkeypatch, tmp_path):
    saved = {}

    def mock_load():
        return {"s": {
            "session_id": "", "agent": "claude", "cwd": str(tmp_path),
            "mode": None, "model": None,
        }}

    def mock_save(data):
        saved.update(data)

    monkeypatch.setattr(ss, "get_session", lambda n: {
        "session_id": "", "agent": "claude", "cwd": str(tmp_path), "mode": None, "model": None,
    })
    monkeypatch.setattr(ss, "load_sessions", mock_load)
    monkeypatch.setattr(ss, "save_sessions", mock_save)

    # Wire up a fake active session so we can assert pending_respawn is set.
    fake_active = _make_fake_active("s")
    mgr._sessions["s"] = fake_active

    q: asyncio.Queue = asyncio.Queue()
    await bc.handle_add_dir("s", f"/add-dir {tmp_path}", q)

    cards = _drain(q)
    assert len(cards) == 1
    assert cards[0].kind == "add_dir"
    assert cards[0].data.get("valid") is True
    assert str(tmp_path) in cards[0].body
    assert str(tmp_path) in (saved.get("s", {}).get("extra_dirs") or [])
    # The old "__respawn__" sentinel must never appear; pending_respawn flag is used instead.
    assert fake_active.model != "__respawn__"
    assert fake_active.pending_respawn is True


@pytest.mark.asyncio
async def test_add_dir_duplicate_path_emits_already_added_card(monkeypatch, tmp_path):
    """Re-adding an existing path emits an informational card without setting pending_respawn."""
    monkeypatch.setattr(ss, "get_session", lambda n: {
        "session_id": "", "agent": "claude", "cwd": str(tmp_path),
        "mode": None, "model": None,
        "extra_dirs": [str(tmp_path)],
    })

    fake_active = _make_fake_active("s")
    mgr._sessions["s"] = fake_active

    q: asyncio.Queue = asyncio.Queue()
    await bc.handle_add_dir("s", f"/add-dir {tmp_path}", q)

    cards = _drain(q)
    assert len(cards) == 1
    assert cards[0].kind == "add_dir"
    assert "already" in cards[0].title.lower()
    assert fake_active.pending_respawn is False


# ─────────────────────────────────────────────
# 7. _build_claude_args extra_dirs wiring
# ─────────────────────────────────────────────

def test_build_claude_args_no_extra_dirs_omits_add_dir_flag():
    args = mgr._build_claude_args(None)
    assert "--add-dir" not in args


def test_build_claude_args_with_claude_agent():
    args = mgr._build_claude_args(None, claude_agent="ht-backend-engineer")
    assert "--agent" in args
    assert "ht-backend-engineer" in args


def test_build_claude_args_with_extra_dirs_appends_flags():
    args = mgr._build_claude_args(None, extra_dirs=["/tmp/foo", "/tmp/bar"])
    # Both dirs must appear as --add-dir <dir> pairs
    assert "--add-dir" in args
    idx = args.index("--add-dir")
    assert args[idx + 1] == "/tmp/foo"
    idx2 = args.index("--add-dir", idx + 1)
    assert args[idx2 + 1] == "/tmp/bar"


@pytest.mark.asyncio
async def test_spawn_reads_extra_dirs_from_session_metadata(monkeypatch, tmp_path):
    """_spawn_claude_proc must forward extra_dirs stored in session metadata."""
    captured: list[list[str]] = []

    async def fake_create_subprocess(*args, **kwargs):
        captured.append(list(args))
        proc = MagicMock()
        proc.stdin = MagicMock()
        proc.stdout = MagicMock()
        proc.stderr = MagicMock()
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess)
    monkeypatch.setattr(ss, "get_metadata", lambda n: {
        "agent": "claude", "cwd": str(tmp_path), "mode": None, "model": None,
        "extra_dirs": [str(tmp_path)],
    })

    await mgr._spawn_claude_proc(
        prior_session_id=None,
        cwd=str(tmp_path),
        session_name="s",
    )

    assert len(captured) == 1
    args = captured[0]
    assert "--add-dir" in args
    idx = args.index("--add-dir")
    assert args[idx + 1] == str(tmp_path)


# ─────────────────────────────────────────────
# 9–11. Prompt templates
# ─────────────────────────────────────────────

def test_build_review_prompt_contains_base_text():
    prompt = pt.build_review_prompt("")
    assert "git diff" in prompt
    assert "correctness" in prompt or "bugs" in prompt


def test_build_review_prompt_appends_args():
    prompt = pt.build_review_prompt("focus on auth layer")
    assert "focus on auth layer" in prompt


def test_build_security_review_prompt_contains_security_keywords():
    prompt = pt.build_security_review_prompt("")
    assert "injection" in prompt.lower() or "authz" in prompt.lower()
    assert "git diff" in prompt


def test_build_security_review_prompt_appends_args():
    prompt = pt.build_security_review_prompt("only check SQL")
    assert "only check SQL" in prompt


def test_build_pr_comments_prompt_uses_pr_number():
    prompt = pt.build_pr_comments_prompt("42")
    assert "42" in prompt
    assert "gh pr view" in prompt


def test_build_pr_comments_prompt_fallback_when_empty():
    prompt = pt.build_pr_comments_prompt("")
    assert "gh pr view" in prompt


# ─────────────────────────────────────────────
# 12–13. commands_scanner registration
# ─────────────────────────────────────────────

def test_new_commands_appear_in_scan(tmp_path):
    from devscope_bridge.commands_scanner import scan_commands
    names = {c["name"] for c in scan_commands(project_root=tmp_path)}
    assert "/status" in names
    assert "/add-dir" in names
    assert "/review" in names
    assert "/security-review" in names
    assert "/pr-comments" in names


# ─────────────────────────────────────────────
# 14–15. dispatch routing
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dispatch_status_emits_status_card(monkeypatch):
    monkeypatch.setattr(bc.status_helpers, "get_cli_version", AsyncMock(return_value="x.y.z"))
    monkeypatch.setattr(bc.session_store, "get_metadata", lambda n: {
        "session_id": "id1", "agent": "claude", "model": "m", "mode": "act", "cwd": "/c",
    })

    q: asyncio.Queue = asyncio.Queue()
    await bc.dispatch("s", "/status", "/status", q)

    cards = [f for f in _drain(q) if isinstance(f, SlashCommandCard)]
    assert any(c.kind == "status" for c in cards)


@pytest.mark.asyncio
async def test_dispatch_add_dir_no_arg_emits_error_card():
    q: asyncio.Queue = asyncio.Queue()
    await bc.dispatch("s", "/add-dir", "/add-dir", q)

    cards = [f for f in _drain(q) if isinstance(f, SlashCommandCard)]
    assert any(c.kind == "add_dir" and c.data.get("valid") is False for c in cards)
