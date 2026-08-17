"""
test_session_commands.py — /interrupt, /ask, and context-recovery preamble.

Covers the session-control commands wired into the WS loop and the
context-preservation fix for forced respawns:

1. /ask (background_ask): empty question, concurrency cap, parallel streaming.
2. _handle_session_command dispatch: /medic, /interrupt (running vs idle), /ask.
3. build_recovery_preamble: rebuilds a summary from a transcript JSONL.
4. run_prompt injects a stashed recovery preamble + emits ContextRecovery.
5. /ask and /interrupt appear in the slash-command menu.
"""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock

import devscope_bridge.background_ask as ba
import devscope_bridge.session_manager as mgr
import devscope_bridge.session_store as store
import devscope_bridge.main as bridge_main
from devscope_bridge.models import (
    AiChunk, AiError, AgentActivity, AskChunk, AskDone, AskStart, ContextRecovery,
)


@pytest.fixture(autouse=True)
def clean_state(tmp_path, monkeypatch):
    # Isolation: run_prompt/build_recovery_preamble read+write through
    # session_store's transcript paths — several tests here use the generic
    # session name "s", which must never touch the real ~/.dev-bridge.
    monkeypatch.setattr(store, "BRIDGE_DIR", tmp_path)
    monkeypatch.setattr(store, "BRIDGE_TRANSCRIPTS_DIR", tmp_path / "chat-transcripts")
    ba._active_asks.clear()
    mgr._sessions.clear()
    yield
    ba._active_asks.clear()
    mgr._sessions.clear()


# ─────────────────────────────────────────────
# Fake separate-process helpers
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


# ─────────────────────────────────────────────
# 1. background_ask
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ask_empty_question_is_rejected():
    q: asyncio.Queue = asyncio.Queue()
    await ba.run_ask("s", q, "   ")
    frames = _drain(q)
    assert any(isinstance(f, AiChunk) and "Usage" in f.text for f in frames)
    assert ba._active_asks.get("s", 0) == 0


@pytest.mark.asyncio
async def test_ask_concurrency_cap():
    q: asyncio.Queue = asyncio.Queue()
    ba._active_asks["s"] = ba._MAX_CONCURRENT  # already at cap
    await ba.run_ask("s", q, "what is X?")
    frames = _drain(q)
    assert any(isinstance(f, AiError) and "concurrent" in f.stderr_tail for f in frames)


@pytest.mark.asyncio
async def test_ask_streams_answer_in_parallel(monkeypatch):
    lines = [
        json.dumps({"type": "stream_event", "event": {"delta": {
            "type": "text_delta", "text": "The answer is 42."}}}),
        json.dumps({"type": "result", "subtype": "success"}),
    ]
    monkeypatch.setattr(ba, "_spawn_ask_proc", AsyncMock(return_value=_fake_proc(lines)))

    q: asyncio.Queue = asyncio.Queue()
    await ba.run_ask("s", q, "what is the answer?")

    frames = _drain(q)
    starts = [f for f in frames if isinstance(f, AskStart)]
    chunks = [f for f in frames if isinstance(f, AskChunk)]
    dones = [f for f in frames if isinstance(f, AskDone)]
    assert len(starts) == 1 and starts[0].question == "what is the answer?"
    assert any("42" in c.text for c in chunks)
    # start/chunk/done all share one question_id
    assert starts[0].question_id == dones[0].question_id
    assert dones[0].ok is True
    assert ba._active_asks.get("s", 0) == 0  # released after run


# ─────────────────────────────────────────────
# 2. _handle_session_command dispatch
# ─────────────────────────────────────────────

class _FakeWS:
    def __init__(self):
        self.sent = []

    async def send_text(self, text):
        self.sent.append(text)


@pytest.mark.asyncio
async def test_command_interrupt_running(monkeypatch):
    calls = []
    monkeypatch.setattr(bridge_main.session_manager, "is_turn_running", lambda n: True)
    monkeypatch.setattr(bridge_main.session_manager, "interrupt_session", lambda n: calls.append(n))
    monkeypatch.setattr(bridge_main.session_manager, "_sessions", {})

    ws = _FakeWS()
    q: asyncio.Queue = asyncio.Queue()
    monkeypatch.setattr(bridge_main, "_command_queue", lambda sn, w, pt: (q, None))

    await bridge_main._handle_session_command(ws, "sess", "/interrupt", "/interrupt", None)
    assert calls == ["sess"]
    assert any(isinstance(f, AgentActivity) and "Interrupting" in f.label for f in _drain(q))


@pytest.mark.asyncio
async def test_command_interrupt_idle(monkeypatch):
    calls = []
    monkeypatch.setattr(bridge_main.session_manager, "is_turn_running", lambda n: False)
    monkeypatch.setattr(bridge_main.session_manager, "interrupt_session", lambda n: calls.append(n))
    q: asyncio.Queue = asyncio.Queue()
    monkeypatch.setattr(bridge_main, "_command_queue", lambda sn, w, pt: (q, None))

    await bridge_main._handle_session_command(_FakeWS(), "sess", "/interrupt", "/interrupt", None)
    assert calls == []  # nothing to interrupt
    assert any(isinstance(f, AgentActivity) and "Nothing" in f.label for f in _drain(q))


@pytest.mark.asyncio
async def test_command_ask_dispatches(monkeypatch):
    got = {}

    async def fake_run_ask(name, q, question):
        got["name"] = name
        got["question"] = question

    # /ask now routes through capability_router.run_on_queue → background_ask.run_ask
    monkeypatch.setattr(
        bridge_main.capability_router.background_ask, "run_ask", fake_run_ask,
    )
    q: asyncio.Queue = asyncio.Queue()
    monkeypatch.setattr(bridge_main, "_command_queue", lambda sn, w, pt: (q, None))

    await bridge_main._handle_session_command(_FakeWS(), "sess", "/ask", "/ask why is the sky blue", None)
    await asyncio.sleep(0.05)
    assert got == {"name": "sess", "question": "why is the sky blue"}


# ─────────────────────────────────────────────
# 3. build_recovery_preamble
# ─────────────────────────────────────────────

def test_build_recovery_preamble_extracts_first_user_and_last_assistant(monkeypatch, tmp_path):
    transcript = tmp_path / "t.jsonl"
    transcript.write_text("\n".join([
        json.dumps({"type": "user", "message": {"content": [{"type": "text", "text": "build feature 238"}]}}),
        json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "starting"}]}}),
        json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "done step 2"}]}}),
    ]))
    monkeypatch.setattr(mgr.session_store, "transcript_path", lambda n: str(transcript))

    preamble = mgr.build_recovery_preamble("s")
    assert preamble is not None
    assert "build feature 238" in preamble        # first user request
    assert "done step 2" in preamble               # latest assistant progress
    assert "context recovery" in preamble.lower()


def test_build_recovery_preamble_none_without_transcript(monkeypatch):
    monkeypatch.setattr(mgr.session_store, "transcript_path", lambda n: None)
    assert mgr.build_recovery_preamble("s") is None


# ─────────────────────────────────────────────
# 3b. read_transcript_turns (shared source for chat ↔ terminal)
# ─────────────────────────────────────────────

def test_read_transcript_turns_parses_and_skips_tool_only(monkeypatch, tmp_path):
    ss = mgr.session_store
    t = tmp_path / "t.jsonl"
    t.write_text("\n".join([
        json.dumps({"type": "user", "message": {"content": [{"type": "text", "text": "q1"}]}}),
        json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "a1"}]}}),
        json.dumps({"type": "user", "message": {"content": [{"type": "tool_result", "content": "x"}]}}),
        json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "a2"}]}}),
        json.dumps({"type": "system", "subtype": "init"}),
    ]))
    monkeypatch.setattr(ss, "transcript_path", lambda n: str(t))
    turns = ss.read_transcript_turns("s")
    assert turns == [
        {"role": "user", "text": "q1"},
        {"role": "assistant", "text": "a1"},
        {"role": "assistant", "text": "a2"},
    ]


def test_read_transcript_turns_empty_without_path(monkeypatch):
    monkeypatch.setattr(mgr.session_store, "transcript_path", lambda n: None)
    assert mgr.session_store.read_transcript_turns("s") == []


def test_transcript_ends_incomplete(monkeypatch, tmp_path):
    ss = mgr.session_store
    incomplete = tmp_path / "i.jsonl"
    incomplete.write_text("\n".join([
        json.dumps({"type": "user", "message": {"content": [{"type": "text", "text": "q"}]}}),
        json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "a"}]}}),
        json.dumps({"type": "user", "message": {"content": [{"type": "text", "text": "q2"}]}}),  # dangling
    ]))
    complete = tmp_path / "c.jsonl"
    complete.write_text("\n".join([
        json.dumps({"type": "user", "message": {"content": [{"type": "text", "text": "q"}]}}),
        json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "a"}]}}),
    ]))

    monkeypatch.setattr(ss, "transcript_path", lambda n: str(incomplete))
    assert ss.transcript_ends_incomplete("s") is True
    monkeypatch.setattr(ss, "transcript_path", lambda n: str(complete))
    assert ss.transcript_ends_incomplete("s") is False


# ─────────────────────────────────────────────
# 4. run_prompt injects the stashed recovery preamble
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_prompt_injects_recovery_preamble(monkeypatch):
    proc = MagicMock()
    proc.returncode = None
    proc.stdin = MagicMock()
    proc.stdin.write = MagicMock()
    proc.stdin.drain = AsyncMock()
    q: asyncio.Queue = asyncio.Queue()
    turn_done = asyncio.Event()
    turn_done.set()
    active = mgr._ActiveSession(
        name="s", session_id="", proc=proc, out_queue=q,
        reader_task=MagicMock(), idle_task=MagicMock(),
        mode=None, model=None, turn_done=turn_done,
    )
    active.pending_preamble = "RECOVERY-SUMMARY"
    mgr._sessions["s"] = active

    monkeypatch.setattr(mgr.session_store, "get_session", lambda n: {"session_id": ""})
    monkeypatch.setattr(mgr, "_session_agent", lambda n: "claude")
    monkeypatch.setattr(mgr, "_session_cwd", lambda n: "/tmp")
    monkeypatch.setattr(mgr, "_session_mode", lambda n: None)
    monkeypatch.setattr(mgr, "_session_model", lambda n: None)
    monkeypatch.setattr(mgr, "build_context_preamble", lambda c: "")

    await mgr.run_prompt("s", "continue please")

    written = proc.stdin.write.call_args[0][0].decode("utf-8")
    assert "RECOVERY-SUMMARY" in written
    assert "continue please" in written
    assert active.pending_preamble is None
    assert any(isinstance(f, ContextRecovery) for f in _drain(q))


@pytest.mark.asyncio
async def test_run_prompt_closes_live_pty_before_spawn(monkeypatch):
    """A chat turn closes any live PTY on the same session (single-owner guarantee)."""
    proc = MagicMock()
    proc.returncode = None
    proc.stdin = MagicMock()
    proc.stdin.write = MagicMock()
    proc.stdin.drain = AsyncMock()
    turn_done = asyncio.Event()
    turn_done.set()
    active = mgr._ActiveSession(
        name="ns", session_id="", proc=proc, out_queue=asyncio.Queue(),
        reader_task=MagicMock(), idle_task=MagicMock(), mode=None, model=None, turn_done=turn_done,
    )
    mgr._sessions["ns"] = active

    monkeypatch.setattr(mgr.session_store, "get_session", lambda n: {"session_id": ""})
    monkeypatch.setattr(mgr, "_session_agent", lambda n: "claude")
    monkeypatch.setattr(mgr, "_session_cwd", lambda n: "/tmp")
    monkeypatch.setattr(mgr, "_session_mode", lambda n: None)
    monkeypatch.setattr(mgr, "_session_model", lambda n: None)
    monkeypatch.setattr(mgr, "build_context_preamble", lambda c: "")

    import devscope_bridge.pty_manager as pm
    closed = []
    monkeypatch.setattr(pm, "terminal_for_session", lambda n: "term-ns-1")
    monkeypatch.setattr(pm, "close_terminal", lambda tid: closed.append(tid))
    # run_prompt force-drops the stale chat after closing the PTY — stub it so the
    # reusable fake session survives for the assertion (real kill would spawn claude).
    monkeypatch.setattr(mgr, "kill_session", AsyncMock())

    await mgr.run_prompt("ns", "hello")
    assert closed == ["term-ns-1"]


@pytest.mark.asyncio
async def test_run_prompt_skips_headless_when_chat_pty_active(monkeypatch):
    """Terminal-first chat PTY owns the session — no competing headless spawn."""
    import devscope_bridge.pty_manager as pm
    from devscope_bridge.models import TurnState

    monkeypatch.setattr(pm, "terminal_for_session", lambda n: "chat-ns")
    spawn = AsyncMock()
    monkeypatch.setattr(mgr, "_spawn_claude_proc", spawn)
    monkeypatch.setattr(mgr.session_store, "get_session", lambda n: {"session_id": "sid"})
    monkeypatch.setattr(mgr, "_session_agent", lambda n: "claude")
    monkeypatch.setattr(mgr, "_session_cwd", lambda n: "/tmp")
    monkeypatch.setattr(mgr, "_session_mode", lambda n: None)
    monkeypatch.setattr(mgr, "_session_model", lambda n: None)
    monkeypatch.setattr(mgr, "build_context_preamble", lambda c: "")

    q = await mgr.run_prompt("ns", "hello")
    assert not spawn.called
    frame = q.get_nowait()
    assert isinstance(frame, TurnState)
    assert frame.running is False


# ─────────────────────────────────────────────
# 5. Slash-menu registration
# ─────────────────────────────────────────────

def test_builtin_commands_include_interrupt_and_ask(tmp_path):
    from devscope_bridge.commands_scanner import scan_commands
    names = {c["name"] for c in scan_commands(project_root=tmp_path)}
    assert {"/medic", "/interrupt", "/ask", "/cursor-ctx"} <= names


def _drain(q: asyncio.Queue) -> list:
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out
