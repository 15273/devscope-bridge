"""
test_background_english_coach.py — Unit tests for the English-coach side-query.

Mirrors the style of test_session_commands.py / background_ask tests:
uses an injected spawn fixture so no real claude subprocess is spawned.

Covers:
(a) Gating — slash-command verbs and empty text are skipped (no frames emitted).
(b) native_lang is injected into the subprocess args.
(c) Per-session concurrency cap: excess coach is silently rejected (no AskStart).
(d) Failing / timeout coach emits AskDone(ok=False) and never raises.
(e) Happy path: AskStart/AskChunk/AskDone stream produced correctly.
(f) UserMsg.coach_enabled / coach_lang fields parse correctly (model contract).
(g) AskStart.kind accepts "english_coach" (model contract).
"""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock

import devscope_bridge.background_english_coach as bec
from devscope_bridge.models import AskChunk, AskDone, AskStart, UserMsg


# ─────────────────────────────────────────────
# Fixtures & helpers
# ─────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clean_coaches():
    bec._active_coaches.clear()
    bec._last_coach_prompt.clear()
    bec._coach_start_locks.clear()
    yield
    bec._active_coaches.clear()
    bec._last_coach_prompt.clear()
    bec._coach_start_locks.clear()


class _FakeStdout:
    """Async-iterable stdout backed by a list of pre-encoded lines."""

    def __init__(self, lines: list[str]) -> None:
        self._lines = [(ln + "\n").encode("utf-8") for ln in lines]
        self._i = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._i >= len(self._lines):
            raise StopAsyncIteration
        line = self._lines[self._i]
        self._i += 1
        return line


def _fake_proc(lines: list[str]) -> MagicMock:
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


def _text_chunk_lines(text: str) -> list[str]:
    return [
        json.dumps({
            "type": "stream_event",
            "event": {"delta": {"type": "text_delta", "text": text}},
        }),
        json.dumps({"type": "result", "subtype": "success"}),
    ]


# ─────────────────────────────────────────────
# (a) Gating — empty text
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_empty_text_skips_coach(monkeypatch):
    """Empty user text must not emit any frames and must not touch the counter."""
    spawned = []
    monkeypatch.setattr(bec, "_spawn_coach_proc", AsyncMock(side_effect=lambda lang, coach_focus=None: spawned.append(lang)))

    q: asyncio.Queue = asyncio.Queue()
    await bec.run_english_coach("sess", q, "   ", "he")

    assert q.empty(), "Expected no frames for empty user text"
    assert not spawned, "Subprocess must not be spawned for empty text"
    assert bec._active_coaches.get("sess", 0) == 0


@pytest.mark.asyncio
async def test_duplicate_prompt_skipped_within_window(monkeypatch):
    monkeypatch.setattr(bec, "_spawn_coach_proc", AsyncMock(return_value=_fake_proc(_text_chunk_lines("ok"))))
    monkeypatch.setattr(bec.session_store, "read_transcript_turns", lambda n: [])

    q: asyncio.Queue = asyncio.Queue()
    await bec.run_english_coach("sess", q, "same question", "he")
    assert not q.empty()
    while not q.empty():
        q.get_nowait()

    q2: asyncio.Queue = asyncio.Queue()
    await bec.run_english_coach("sess", q2, "same question", "he")
    assert q2.empty(), "Duplicate coach within dedupe window must emit nothing"


# ─────────────────────────────────────────────
# (b) native_lang injected into subprocess args
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_native_lang_injected_into_args(monkeypatch):
    """native_lang must appear inside the system-prompt arg sent to the subprocess."""
    captured_args: list[list[str]] = []

    async def fake_spawn(lang: str, coach_focus: list[str] | None = None) -> MagicMock:
        args = bec._build_coach_args(lang, coach_focus or [])
        captured_args.append(args)
        return _fake_proc(_text_chunk_lines("Ganz gut!"))

    monkeypatch.setattr(bec, "_spawn_coach_proc", fake_spawn)
    # Suppress session_store transcript lookup (no real session)
    monkeypatch.setattr(bec.session_store, "read_transcript_turns", lambda n: [])

    q: asyncio.Queue = asyncio.Queue()
    await bec.run_english_coach("sess", q, "I writed the code", "de")

    assert captured_args, "Subprocess must have been spawned"
    args = captured_args[0]
    system_prompt_arg = args[args.index("--append-system-prompt") + 1]
    assert "de" in system_prompt_arg, (
        f"Expected native_lang 'de' in system prompt, got: {system_prompt_arg[:200]}"
    )


# ─────────────────────────────────────────────
# (c) Concurrency cap
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_concurrency_cap_rejects_excess(monkeypatch):
    """When the per-session cap is reached, the coach emits no frames at all."""
    bec._active_coaches["sess"] = bec._MAX_CONCURRENT

    spawned = []
    monkeypatch.setattr(bec, "_spawn_coach_proc", AsyncMock(side_effect=lambda lang, coach_focus=None: spawned.append(lang)))

    q: asyncio.Queue = asyncio.Queue()
    await bec.run_english_coach("sess", q, "Hello world", "he")

    assert q.empty(), "No frames must be emitted when cap is reached"
    assert not spawned, "Subprocess must not be spawned when cap is reached"
    # Counter must not have been incremented
    assert bec._active_coaches["sess"] == bec._MAX_CONCURRENT


# ─────────────────────────────────────────────
# (d) Subprocess failure → AskDone(ok=False)
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_subprocess_exception_emits_done_not_ok(monkeypatch):
    """A subprocess error must emit AskDone(ok=False) and must not raise."""
    async def failing_spawn(lang: str, coach_focus: list[str] | None = None) -> MagicMock:
        raise RuntimeError("claude binary not found")

    monkeypatch.setattr(bec, "_spawn_coach_proc", failing_spawn)
    monkeypatch.setattr(bec.session_store, "read_transcript_turns", lambda n: [])

    q: asyncio.Queue = asyncio.Queue()
    # Must not raise
    await bec.run_english_coach("sess", q, "I has a error", "he")

    frames = _drain(q)
    dones = [f for f in frames if isinstance(f, AskDone)]
    assert dones, "AskDone frame must be emitted on failure"
    assert dones[0].ok is False, "AskDone.ok must be False on failure"
    assert bec._active_coaches.get("sess", 0) == 0, "Counter must be released after failure"


@pytest.mark.asyncio
async def test_timeout_emits_done_not_ok(monkeypatch):
    """A subprocess that hangs past _TIMEOUT_S must yield AskDone(ok=False)."""

    async def hanging_stream(*_args, **_kwargs):
        await asyncio.sleep(9999)

    monkeypatch.setattr(bec, "_spawn_coach_proc", AsyncMock(return_value=_fake_proc([])))
    monkeypatch.setattr(bec, "_stream_coach_output", hanging_stream)
    monkeypatch.setattr(bec.session_store, "read_transcript_turns", lambda n: [])
    # Shorten timeout so the test finishes fast
    monkeypatch.setattr(bec, "_TIMEOUT_S", 0.05)

    q: asyncio.Queue = asyncio.Queue()
    await bec.run_english_coach("sess", q, "I has a error", "he")

    frames = _drain(q)
    dones = [f for f in frames if isinstance(f, AskDone)]
    chunks = [f for f in frames if isinstance(f, AskChunk)]

    assert dones and dones[0].ok is False, "AskDone(ok=False) must be emitted on timeout"
    assert any("timed out" in (c.text or "") for c in chunks), (
        "A warning chunk must mention timeout"
    )
    assert bec._active_coaches.get("sess", 0) == 0


# ─────────────────────────────────────────────
# (e) Happy path — correct frame sequence
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_happy_path_streams_ask_start_chunks_done(monkeypatch):
    """Successful coach run must emit AskStart → AskChunk(s) → AskDone(ok=True)."""
    lesson = "נראה טוב! רק תיקון קטן: 'I wrote' ולא 'I writed'."
    lines = _text_chunk_lines(lesson)
    monkeypatch.setattr(bec, "_spawn_coach_proc", AsyncMock(return_value=_fake_proc(lines)))
    monkeypatch.setattr(bec.session_store, "read_transcript_turns", lambda n: [])

    q: asyncio.Queue = asyncio.Queue()
    await bec.run_english_coach("sess", q, "I writed the feature", "he")

    frames = _drain(q)
    starts = [f for f in frames if isinstance(f, AskStart)]
    chunks = [f for f in frames if isinstance(f, AskChunk)]
    dones = [f for f in frames if isinstance(f, AskDone)]

    assert len(starts) == 1
    assert starts[0].kind == "english_coach"
    assert starts[0].question == "I writed the feature"
    assert any(lesson in c.text for c in chunks)
    assert len(dones) == 1 and dones[0].ok is True
    # All frames share one question_id
    assert starts[0].question_id == dones[0].question_id
    assert bec._active_coaches.get("sess", 0) == 0


# ─────────────────────────────────────────────
# (f) UserMsg model — coach fields parse correctly
# ─────────────────────────────────────────────

def test_user_msg_coach_fields_defaults():
    msg = UserMsg(text="hello")
    assert msg.coach_enabled is False
    assert msg.coach_lang == "he"


def test_user_msg_coach_fields_explicit():
    msg = UserMsg(text="hello", coach_enabled=True, coach_lang="ar")
    assert msg.coach_enabled is True
    assert msg.coach_lang == "ar"


def test_user_msg_ignores_unknown_fields():
    """Extra JSON keys must not blow up deserialization (Pydantic v2 default)."""
    data = {
        "type": "user_msg",
        "text": "fix it",
        "coach_enabled": True,
        "coach_lang": "ru",
    }
    msg = UserMsg.model_validate(data)
    assert msg.coach_enabled is True
    assert msg.coach_lang == "ru"


# ─────────────────────────────────────────────
# (g) AskStart model — "english_coach" is a valid kind
# ─────────────────────────────────────────────

def test_ask_start_english_coach_kind():
    frame = AskStart(
        session="s",
        question_id="abc123",
        question="my question",
        kind="english_coach",
    )
    assert frame.kind == "english_coach"
    # Ensure the default is still "ask"
    default_frame = AskStart(session="s", question_id="x", question="q")
    assert default_frame.kind == "ask"
