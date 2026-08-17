"""
test_compact_service.py — Tests for compact_service and /compact honesty.

Coverage
--------
1. assemble_transcript_text: reads all user+assistant turns from JSONL.
2. assemble_transcript_text: caps at _TRANSCRIPT_CHAR_CAP (tail-biased).
3. assemble_transcript_text: returns "" when transcript_path returns None.
4. summarize_transcript: returns the summary text from a fake subprocess.
5. summarize_transcript: returns None on timeout.
6. do_compact: returns real summary + True when summarizer succeeds.
7. do_compact: returns fallback preamble + False when transcript is empty.
8. do_compact: returns fallback preamble + False when summarizer returns None.
9. handle_compact: emits interim card then final card with honest title.
10. handle_compact (fallback path): final card title says "fallback".
"""

import asyncio
import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import devscope_bridge.compact_service as cs
import devscope_bridge.builtin_commands as bc


# ─────────────────────────────────────────────
# Fake subprocess helpers
# ─────────────────────────────────────────────

class _FakeStdout:
    def __init__(self, lines):
        self._lines = [(l + "\n").encode("utf-8") for l in lines]
        self._i = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._i >= len(self._lines):
            raise StopAsyncIteration
        line = self._lines[self._i]
        self._i += 1
        return line


def _fake_proc(lines):
    proc = MagicMock()
    proc.returncode = 0
    proc.stdout = _FakeStdout(lines)
    proc.stdin = MagicMock()
    proc.stdin.write = MagicMock()
    proc.stdin.drain = AsyncMock()
    proc.stdin.close = MagicMock()
    proc.terminate = MagicMock()
    return proc


def _drain(q: asyncio.Queue) -> list:
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


# ─────────────────────────────────────────────
# 1–3. assemble_transcript_text
# ─────────────────────────────────────────────

def test_assemble_transcript_text_reads_all_turns(monkeypatch, tmp_path):
    transcript = tmp_path / "t.jsonl"
    transcript.write_text("\n".join([
        json.dumps({"type": "user", "message": {"content": [{"type": "text", "text": "hello"}]}}),
        json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "world"}]}}),
        json.dumps({"type": "user", "message": {"content": [{"type": "text", "text": "more stuff"}]}}),
        json.dumps({"type": "system", "subtype": "init"}),  # must be skipped
    ]))
    monkeypatch.setattr(cs.session_store, "transcript_path", lambda n: str(transcript))

    text = cs.assemble_transcript_text("s")
    assert "[USER]" in text
    assert "hello" in text
    assert "[ASSISTANT]" in text
    assert "world" in text
    assert "more stuff" in text
    assert "system" not in text.lower() or "init" not in text


def test_assemble_transcript_text_caps_at_char_limit(monkeypatch, tmp_path):
    # Build a transcript larger than the cap
    big_turn = "x" * (cs._TRANSCRIPT_CHAR_CAP // 2)
    lines = [
        json.dumps({"type": "user", "message": {"content": [{"type": "text", "text": big_turn}]}}),
        json.dumps({"type": "user", "message": {"content": [{"type": "text", "text": big_turn}]}}),
        json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "tail marker"}]}}),
    ]
    transcript = tmp_path / "big.jsonl"
    transcript.write_text("\n".join(lines))
    monkeypatch.setattr(cs.session_store, "transcript_path", lambda n: str(transcript))

    text = cs.assemble_transcript_text("s")
    assert len(text) <= cs._TRANSCRIPT_CHAR_CAP + len("[...transcript truncated...]\n\n")
    # Tail is preserved: the last assistant turn must appear.
    assert "tail marker" in text


def test_assemble_transcript_text_empty_without_path(monkeypatch, tmp_path):
    monkeypatch.setattr(cs.session_store, "transcript_path", lambda n: None)
    monkeypatch.setattr(cs.session_store, "BRIDGE_TRANSCRIPTS_DIR", tmp_path / "empty")
    assert cs.assemble_transcript_text("s") == ""


# ─────────────────────────────────────────────
# 4–5. summarize_transcript
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_summarize_transcript_returns_summary_text(monkeypatch):
    lines = [
        json.dumps({"type": "stream_event", "event": {"delta": {
            "type": "text_delta", "text": "Goal: build feature. Status: done."}}}),
        json.dumps({"type": "result", "subtype": "success"}),
    ]
    monkeypatch.setattr(cs, "_spawn_summarizer_proc", AsyncMock(return_value=_fake_proc(lines)))

    result = await cs.summarize_transcript("some transcript text", "")
    assert result == "Goal: build feature. Status: done."


@pytest.mark.asyncio
async def test_summarize_transcript_returns_none_on_timeout(monkeypatch):
    async def _slow_collect(proc):
        await asyncio.sleep(999)
        return ""

    monkeypatch.setattr(cs, "_spawn_summarizer_proc", AsyncMock(return_value=_fake_proc([])))
    monkeypatch.setattr(cs, "_SUMMARIZE_TIMEOUT_S", 0.01)

    result = await cs.summarize_transcript("some text", "")
    assert result is None


# ─────────────────────────────────────────────
# 6–8. do_compact
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_assemble_transcript_text_uses_bridge_when_no_claude_jsonl(tmp_path, monkeypatch):
    import devscope_bridge.session_store as store

    monkeypatch.setattr(store, "transcript_path", lambda n: None)
    monkeypatch.setattr(store, "BRIDGE_TRANSCRIPTS_DIR", tmp_path)
    store.append_bridge_turn("s", "user", "Jobright overlay on same page")
    store.append_bridge_turn("s", "assistant", "Compared to jr_inject pattern")

    text = cs.assemble_transcript_text("s")
    assert "Jobright overlay" in text
    assert "jr_inject" in text


@pytest.mark.asyncio
async def test_do_compact_real_summary_when_summarizer_succeeds(monkeypatch):
    monkeypatch.setattr(cs, "assemble_transcript_text", lambda n: "user turn\nassistant turn")
    monkeypatch.setattr(cs, "summarize_transcript", AsyncMock(return_value="Compact summary text"))

    preamble, was_real = await cs.do_compact("s", "")
    assert was_real is True
    assert "Compact summary text" in preamble
    assert "[Bridge compact]" in preamble


@pytest.mark.asyncio
async def test_do_compact_fallback_when_no_transcript(monkeypatch):
    monkeypatch.setattr(cs, "assemble_transcript_text", lambda n: "")
    fallback_preamble = "[Bridge context recovery] original request…"
    monkeypatch.setattr(cs.session_manager, "build_recovery_preamble", lambda n: fallback_preamble)

    preamble, was_real = await cs.do_compact("s", "")
    assert was_real is False
    assert fallback_preamble in preamble


def test_persist_session_notes_writes_file(tmp_path, monkeypatch):
    monkeypatch.setattr(cs.session_store, "BRIDGE_DIR", tmp_path)
    path = cs.persist_session_notes("sess", "[Bridge compact] summary text", True)
    assert path is not None
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "sess" in text
    assert "summary text" in text


@pytest.mark.asyncio
async def test_do_compact_keeps_transcript_tail_when_summarizer_returns_none(monkeypatch):
    # When the summarizer fails but we DO have a transcript, keep the raw tail
    # verbatim rather than dropping to the thin recovery extract.
    transcript = "[USER]\nfix the recorder\n\n[ASSISTANT]\nswitched to mp4 export"
    summarize = AsyncMock(return_value=None)
    monkeypatch.setattr(cs, "assemble_transcript_text", lambda n: transcript)
    monkeypatch.setattr(cs, "summarize_transcript", summarize)

    preamble, was_real = await cs.do_compact("s", "")
    assert was_real is False
    assert "mp4 export" in preamble
    assert "included verbatim" in preamble
    # Retried before giving up.
    assert summarize.await_count == cs._SUMMARIZE_MAX_ATTEMPTS


@pytest.mark.asyncio
async def test_do_compact_recovery_extract_when_no_transcript(monkeypatch):
    monkeypatch.setattr(cs, "assemble_transcript_text", lambda n: "")
    monkeypatch.setattr(cs.session_manager, "build_recovery_preamble", lambda n: "fallback text")

    preamble, was_real = await cs.do_compact("s", "")
    assert was_real is False
    assert "fallback text" in preamble


# ─────────────────────────────────────────────
# 9–10. handle_compact honest card titles
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_handle_compact_emits_two_cards_real_summary(monkeypatch, tmp_path):
    # Isolation: apply_compact_reset (via handle_compact) writes through to
    # session_store.reset_bridge_transcript — must never touch the real
    # ~/.dev-bridge (session name "s" here is a test placeholder, not real).
    monkeypatch.setattr(bc.session_store, "BRIDGE_DIR", tmp_path)
    monkeypatch.setattr(bc.session_store, "BRIDGE_TRANSCRIPTS_DIR", tmp_path / "chat-transcripts")
    monkeypatch.setattr(
        bc.compact_service, "guarded_compact",
        AsyncMock(return_value=cs.CompactRun(ok=True, preamble="summary preamble", was_real_summary=True)),
    )
    monkeypatch.setattr(bc.session_store, "clear_session_id", lambda n: None)
    monkeypatch.setattr(bc.session_manager, "kill_session", AsyncMock())
    monkeypatch.setattr(bc.session_reader, "reset_session_usage", lambda n: None)
    bc.pending_compact_preambles.clear()

    q: asyncio.Queue = asyncio.Queue()
    await bc.handle_compact("s", "/compact", q)

    from devscope_bridge.models import SlashCommandCard
    cards = [f for f in _drain(q) if isinstance(f, SlashCommandCard)]
    assert len(cards) == 2
    interim, final = cards
    assert interim.data.get("status") == "in_progress"
    assert final.data.get("was_real_summary") is True
    assert "fallback" not in final.title.lower()
    assert bc.pending_compact_preambles.get("s") == "summary preamble"


@pytest.mark.asyncio
async def test_handle_compact_emits_two_cards_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(bc.session_store, "BRIDGE_DIR", tmp_path)
    monkeypatch.setattr(bc.session_store, "BRIDGE_TRANSCRIPTS_DIR", tmp_path / "chat-transcripts")
    monkeypatch.setattr(
        bc.compact_service, "guarded_compact",
        AsyncMock(return_value=cs.CompactRun(ok=True, preamble="fallback note", was_real_summary=False)),
    )
    monkeypatch.setattr(bc.session_store, "clear_session_id", lambda n: None)
    monkeypatch.setattr(bc.session_manager, "kill_session", AsyncMock())
    monkeypatch.setattr(bc.session_reader, "reset_session_usage", lambda n: None)
    bc.pending_compact_preambles.clear()

    q: asyncio.Queue = asyncio.Queue()
    await bc.handle_compact("s", "/compact", q)

    from devscope_bridge.models import SlashCommandCard
    cards = [f for f in _drain(q) if isinstance(f, SlashCommandCard)]
    assert len(cards) == 2
    _, final = cards
    assert "fallback" in final.title.lower()
    assert bc.pending_compact_preambles.get("s") == "fallback note"


# ─────────────────────────────────────────────
# 11–13. guarded_compact (A7) — serialization + non-destructive abort
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_guarded_compact_success_emits_running_then_done(monkeypatch):
    monkeypatch.setattr(cs, "assemble_transcript_text", lambda n: "user turn\nassistant turn")
    monkeypatch.setattr(cs, "do_compact", AsyncMock(return_value=("summary preamble", True)))
    cs._compact_locks.clear()

    q: asyncio.Queue = asyncio.Queue()
    result = await cs.guarded_compact("s", "", q)

    assert result.ok is True
    assert result.was_real_summary is True
    assert result.preamble == "summary preamble"
    activities = _drain(q)
    assert [a.status for a in activities] == ["running", "done"]
    assert all(a.label == "Compacting session…" for a in activities)


@pytest.mark.asyncio
async def test_guarded_compact_aborts_when_summarizer_fails_on_real_transcript(monkeypatch):
    """RC-5/RC-6: a real transcript existed but the summarizer produced nothing —
    guarded_compact must signal abort (ok=False) so the caller does NOT wipe
    session_id/transcript, unlike do_compact() which still returns a usable
    (but non-real) fallback preamble on its own."""
    monkeypatch.setattr(cs, "assemble_transcript_text", lambda n: "user turn\nassistant turn")
    monkeypatch.setattr(cs, "do_compact", AsyncMock(return_value=("raw tail fallback", False)))
    cs._compact_locks.clear()

    q: asyncio.Queue = asyncio.Queue()
    result = await cs.guarded_compact("s", "", q)

    assert result.ok is False
    assert result.skipped == "summarizer_failed"
    activities = _drain(q)
    assert activities[-1].status == "error"


@pytest.mark.asyncio
async def test_guarded_compact_no_transcript_is_not_an_abort(monkeypatch):
    """Empty transcript (nothing to lose) is a normal fallback, not an abort."""
    monkeypatch.setattr(cs, "assemble_transcript_text", lambda n: "")
    monkeypatch.setattr(cs, "do_compact", AsyncMock(return_value=("fallback text", False)))
    cs._compact_locks.clear()

    q: asyncio.Queue = asyncio.Queue()
    result = await cs.guarded_compact("s", "", q)

    assert result.ok is True
    assert result.was_real_summary is False
    assert result.preamble == "fallback text"


@pytest.mark.asyncio
async def test_guarded_compact_second_caller_skips_while_locked(monkeypatch):
    """A7: concurrent compacts on the same session — second caller no-ops."""
    started = asyncio.Event()
    release = asyncio.Event()

    async def _slow_do_compact(name, extra):
        started.set()
        await release.wait()
        return "summary", True

    monkeypatch.setattr(cs, "assemble_transcript_text", lambda n: "some transcript")
    monkeypatch.setattr(cs, "do_compact", _slow_do_compact)
    cs._compact_locks.clear()

    q1: asyncio.Queue = asyncio.Queue()
    q2: asyncio.Queue = asyncio.Queue()
    first = asyncio.create_task(cs.guarded_compact("dup-sess", "", q1))
    await started.wait()

    second_result = await cs.guarded_compact("dup-sess", "", q2)
    assert second_result.ok is False
    assert second_result.skipped == "already_compacting"

    release.set()
    first_result = await first
    assert first_result.ok is True


@pytest.mark.asyncio
async def test_apply_compact_reset_clears_claude_session(monkeypatch):
    cleared = []
    killed = []
    monkeypatch.setattr(cs.session_store, "clear_session_id", lambda n: cleared.append(n))
    monkeypatch.setattr(cs.session_manager, "kill_session", AsyncMock(side_effect=lambda n: killed.append(n)))
    monkeypatch.setattr(cs.session_reader, "reset_session_usage", lambda n: None)
    monkeypatch.setattr(cs.session_store, "get_session", lambda n: {"agent": "claude"})
    monkeypatch.setattr(cs.session_store, "reset_bridge_transcript", lambda n, seed_turns=None: None)
    monkeypatch.setattr(cs, "persist_session_notes", lambda *a, **k: None)

    await cs.apply_compact_reset("s", "preamble text", True)

    assert cleared == ["s"]
    assert killed == ["s"]
