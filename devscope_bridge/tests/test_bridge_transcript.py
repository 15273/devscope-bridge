"""Bridge-owned transcript for Cursor sessions and context recovery."""
import json

import devscope_bridge.session_manager as mgr
import devscope_bridge.session_store as store


def test_append_and_read_bridge_turns(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "BRIDGE_TRANSCRIPTS_DIR", tmp_path)
    store.append_bridge_turn("cursor-sess", "user", "fix whatsapp inject")
    store.append_bridge_turn("cursor-sess", "assistant", "patched wa_store_runner")
    turns = store.read_transcript_turns("cursor-sess")
    assert len(turns) == 2
    assert turns[0]["role"] == "user"
    assert "whatsapp" in turns[0]["text"]


def test_recovery_preamble_from_bridge_transcript(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "BRIDGE_TRANSCRIPTS_DIR", tmp_path)
    monkeypatch.setattr(store, "transcript_path", lambda n: None)
    store.append_bridge_turn("s", "user", "reload the extension")
    store.append_bridge_turn("s", "assistant", "built and reloaded devscope")
    store.append_bridge_turn("s", "user", "בוצע")

    preamble = mgr.build_recovery_preamble("s")
    assert preamble is not None
    assert "reload the extension" in preamble
    assert "built and reloaded" in preamble
    assert "בוצע" in preamble
    assert "בוצע" in preamble or "done" in preamble.lower()


def test_cursor_short_reply_triggers_recovery_with_chat_id():
    assert mgr._cursor_needs_recovery_preamble("בוצע", "existing-chat-id") is True
    assert mgr._cursor_needs_recovery_preamble("done", "existing-chat-id") is True
    assert mgr._cursor_needs_recovery_preamble("", None) is True
    long_msg = "x" * 81
    assert mgr._cursor_needs_recovery_preamble(long_msg, "existing-chat-id") is False
    assert mgr._cursor_needs_recovery_preamble(long_msg, None) is True


def test_reset_bridge_transcript_clears_stale_history(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "BRIDGE_TRANSCRIPTS_DIR", tmp_path)
    monkeypatch.setattr(store, "transcript_path", lambda n: None)
    store.append_bridge_turn("s", "user", "old message one")
    store.append_bridge_turn("s", "assistant", "old reply one")
    store.reset_bridge_transcript("s", seed_turns=[{"role": "assistant", "text": "[Bridge compact] summary"}])
    turns = store.read_transcript_turns("s")
    assert len(turns) == 1
    assert turns[0]["text"].startswith("[Bridge compact]")
    preamble = mgr.build_recovery_preamble("s")
    assert preamble is not None
    assert "old message one" not in preamble


def test_claude_transcript_preferred_over_bridge(tmp_path, monkeypatch):
    claude_file = tmp_path / "claude.jsonl"
    claude_file.write_text(
        json.dumps({"type": "user", "message": {"content": "from claude jsonl"}}) + "\n"
    )
    monkeypatch.setattr(store, "transcript_path", lambda n: str(claude_file))
    monkeypatch.setattr(store, "BRIDGE_TRANSCRIPTS_DIR", tmp_path / "bridge")
    store.append_bridge_turn("s", "user", "from bridge only")

    turns = store.read_transcript_turns("s")
    assert turns[0]["text"] == "from claude jsonl"


def _claude_entry(role: str, text: str) -> str:
    return json.dumps(
        {"type": role, "message": {"content": [{"type": "text", "text": text}]}}
    ) + "\n"


def test_machinery_user_entries_filtered_from_claude_transcript(tmp_path, monkeypatch):
    """CLI-generated user entries (interrupt/continue, task notifications,
    approval echoes, compact continuations) must not surface as turns — they
    split one assistant turn into two and cause duplicate bubbles in the panel."""
    claude_file = tmp_path / "claude.jsonl"
    claude_file.write_text(
        _claude_entry("user", "redesign the mentor studio")
        + _claude_entry("assistant", "Reading the relevant files first.")
        + _claude_entry("user", "[Request interrupted by user]")
        + _claude_entry("user", "Continue from where you left off.")
        + _claude_entry("assistant", "Done — two root causes found.")
        + _claude_entry("user", "<task-notification> <task-id>abc</task-id> finished")
        + _claude_entry("user", "The user approved running Bash. Execute it now.")
        + _claude_entry("user", "This session is being continued from a previous conversation.")
        + _claude_entry("user", "Base directory for this skill: /Users/x/.claude/skills/foo")
        + _claude_entry("user", "[Bridge compact] Summary only, no user prompt attached.")
        + _claude_entry("user", "סכם בעברית")
        + _claude_entry("assistant", "סיכום: תוקנו שתי בעיות.")
    )
    monkeypatch.setattr(store, "transcript_path", lambda n: str(claude_file))

    turns = store.read_transcript_turns("s")

    assert [(t["role"], t["text"]) for t in turns] == [
        ("user", "redesign the mentor studio"),
        ("assistant", "Reading the relevant files first."),
        ("assistant", "Done — two root causes found."),
        ("user", "סכם בעברית"),
        ("assistant", "סיכום: תוקנו שתי בעיות."),
    ]


def test_compact_seed_yields_embedded_user_message(tmp_path, monkeypatch):
    """A '[Bridge compact]' seed = summary + PAGE CONTEXT + the real message the
    user typed. The message must surface as the user turn; the summary must not."""
    seed = (
        "[Bridge compact] The conversation was summarized by a one-shot process.\n\n"
        "---\n\n--- PAGE CONTEXT ---\ntab_id=1 url=https://x\n--- END CONTEXT ---\n\n"
        "יש לנו טסטים להכל?"
    )
    claude_file = tmp_path / "claude.jsonl"
    claude_file.write_text(
        _claude_entry("user", seed)
        + _claude_entry("assistant", "בודק את הטסטים.")
    )
    monkeypatch.setattr(store, "transcript_path", lambda n: str(claude_file))

    turns = store.read_transcript_turns("s")

    assert [(t["role"], t["text"]) for t in turns] == [
        ("user", "יש לנו טסטים להכל?"),
        ("assistant", "בודק את הטסטים."),
    ]


def test_real_steering_message_survives_machinery_filter(tmp_path, monkeypatch):
    """A message the user actually typed mid-turn (steering) is kept even when
    surrounded by interrupt/continue machinery entries."""
    claude_file = tmp_path / "claude.jsonl"
    claude_file.write_text(
        _claude_entry("assistant", "Working on the CSS scope...")
        + _claude_entry("user", "[Request interrupted by user]")
        + _claude_entry("user", "סיימת?")
        + _claude_entry("assistant", "כמעט — מסיים את הבדיקה.")
    )
    monkeypatch.setattr(store, "transcript_path", lambda n: str(claude_file))

    turns = store.read_transcript_turns("s")

    assert [(t["role"], t["text"]) for t in turns] == [
        ("assistant", "Working on the CSS scope..."),
        ("user", "סיימת?"),
        ("assistant", "כמעט — מסיים את הבדיקה."),
    ]
