"""
test_watchdog_medic.py — Tests for the Watchdog Medic.

The medic is a SEPARATE diagnostic agent the bridge spawns when a session goes
silent mid-turn (a tier below the destructive hard cap).  It captures a
diagnostics bundle, streams findings to the panel, and may apply a scoped fix.

Coverage
--------
1. DIAGNOSTICS: collect_diagnostics returns the expected bundle shape and reads
   relay + session + recent-event state.
2. RECENT EVENTS: the session_reader ring buffer records and returns event
   summaries (with tool names), capped at _RECENT_EVENTS_MAX.
3. RUN_MEDIC STREAMS: run_medic emits WatchdogReport(start) + AiChunk text +
   WatchdogReport(done), and sets/clears medic_active around the run.
4. ONE PER SESSION: a second run_medic while one is in flight is a no-op.
5. MEDIC TIER + HARD-CAP DEFERRAL: _watchdog_loop calls medic_fn at the medic
   threshold and DEFERS the hard cap while medic_active is set, then fires the
   hard cap once the medic clears.
"""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock

import devscope_bridge.session_reader as sr
import devscope_bridge.watchdog_medic as medic
from devscope_bridge.models import AgentActivity, AiChunk, AiError, WatchdogReport


@pytest.fixture(autouse=True)
def clean_medic_state():
    medic._active_medics.clear()
    sr._recent_events.clear()
    yield
    medic._active_medics.clear()
    sr._recent_events.clear()


# ─────────────────────────────────────────────
# 1. Diagnostics bundle
# ─────────────────────────────────────────────

def test_collect_diagnostics_shape(monkeypatch):
    monkeypatch.setattr(medic.session_manager, "get_session_state", lambda n: None)
    monkeypatch.setattr(medic.session_store, "get_session", lambda n: None)
    monkeypatch.setattr(medic, "_resolve_transcript_path", lambda n: None)
    monkeypatch.setattr(medic.browser_relay, "has_active_ws", lambda n: True)
    monkeypatch.setattr(medic.browser_relay, "_pending_actions", {"a1": object(), "a2": object()})
    sr.record_recent_event("sess", {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Bash"},
    ]}})

    diag = medic.collect_diagnostics("sess", 182.4, trigger="manual")

    assert diag["session"] == "sess"
    assert diag["trigger"] == "manual"
    assert diag["agent"] == "claude"
    assert diag["silent_for_s"] == 182.4
    assert diag["session_state"] is None
    assert diag["transcript_path"] is None
    assert diag["extension_ws_connected"] is True
    assert diag["pending_browser_actions"] == 2
    assert diag["recent_events"] == [{"type": "assistant", "tools": ["Bash"]}]


def test_collect_diagnostics_cursor_uses_bridge_transcript(monkeypatch, tmp_path):
    ss = medic.session_store
    bridge_dir = tmp_path / "chat-transcripts"
    bridge_dir.mkdir(parents=True)
    bridge_file = bridge_dir / "jobright_cur.jsonl"
    bridge_file.write_text('{"role":"user","text":"hi"}\n', encoding="utf-8")

    monkeypatch.setattr(ss, "get_session", lambda n: {"agent": "cursor", "session_id": "uuid-1"})
    monkeypatch.setattr(ss, "transcript_path", lambda n: None)
    monkeypatch.setattr(ss, "BRIDGE_TRANSCRIPTS_DIR", bridge_dir)
    monkeypatch.setattr(
        medic.session_manager,
        "get_session_state",
        lambda n: {"agent": "cursor", "turn_done": False, "pending_turns": 1},
    )
    monkeypatch.setattr(medic.browser_relay, "has_active_ws", lambda n: False)
    monkeypatch.setattr(medic.browser_relay, "_pending_actions", {})

    diag = medic.collect_diagnostics("jobright_cur", 0.0, trigger="manual")

    assert diag["agent"] == "cursor"
    assert diag["transcript_path"] == str(bridge_file)
    assert diag["session_state"]["pending_turns"] == 1


def test_transcript_path_globs_by_session_id(monkeypatch, tmp_path):
    ss = medic.session_store
    monkeypatch.setattr(ss, "get_session", lambda n: {"session_id": "sid-xyz"})
    monkeypatch.setattr(ss.Path, "home", lambda: tmp_path)
    proj = tmp_path / ".claude" / "projects" / "-some-proj"
    proj.mkdir(parents=True)
    transcript = proj / "sid-xyz.jsonl"
    transcript.write_text("{}\n")

    assert ss.transcript_path("sess") == str(transcript)


def test_transcript_path_none_without_session_id(monkeypatch):
    monkeypatch.setattr(medic.session_store, "get_session", lambda n: None)
    assert medic.session_store.transcript_path("sess") is None


# ─────────────────────────────────────────────
# 2. Recent-event ring buffer
# ─────────────────────────────────────────────

def test_recent_events_records_and_caps():
    for i in range(sr._RECENT_EVENTS_MAX + 5):
        sr.record_recent_event("s", {"type": "stream_event", "n": i})
    events = sr.get_recent_events("s")
    assert len(events) == sr._RECENT_EVENTS_MAX  # capped
    assert all(e["type"] == "stream_event" for e in events)


def test_recent_events_extracts_tools_and_subtype():
    sr.record_recent_event("s", {"type": "system", "subtype": "init"})
    sr.record_recent_event("s", {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Read"},
        {"type": "tool_use", "name": "Edit"},
        {"type": "text", "text": "hi"},
    ]}})
    events = sr.get_recent_events("s")
    assert events[0] == {"type": "system", "subtype": "init"}
    assert events[1] == {"type": "assistant", "tools": ["Read", "Edit"]}


# ─────────────────────────────────────────────
# Fake medic process helpers
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


def _fake_medic_proc(lines):
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
# 3. run_medic streams report + toggles medic_active
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_medic_streams_and_toggles_active(monkeypatch):
    monkeypatch.setattr(medic.session_manager, "get_session_state", lambda n: None)
    monkeypatch.setattr(medic.session_store, "get_session", lambda n: None)

    lines = [
        json.dumps({"type": "stream_event", "event": {"delta": {
            "type": "text_delta", "text": "Root cause: orphaned browser Future."}}}),
        json.dumps({"type": "result", "subtype": "success"}),
    ]
    proc = _fake_medic_proc(lines)
    monkeypatch.setattr(medic, "_spawn_medic_proc", AsyncMock(return_value=proc))

    q: asyncio.Queue = asyncio.Queue()
    medic_active = asyncio.Event()

    await medic.run_medic("sess", q, medic_active, elapsed_s=190.0)

    # medic_active must be cleared after the run completes
    assert not medic_active.is_set()
    assert "sess" not in medic._active_medics
    # the medic prompt was written to stdin
    assert proc.stdin.write.called

    frames = []
    while not q.empty():
        frames.append(q.get_nowait())

    reports = [f for f in frames if isinstance(f, WatchdogReport)]
    phases = [r.phase for r in reports]
    assert phases[0] == "start"
    assert reports[0].diagnostics is not None
    assert "chunk" in phases
    assert phases[-1] == "done"

    chunks = [f for f in frames if isinstance(f, AiChunk)]
    assert any("orphaned browser Future" in c.text for c in chunks)
    assert any(isinstance(f, AgentActivity) and "Medic" in f.label for f in frames)


# ─────────────────────────────────────────────
# 4. One medic per session
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_medic_one_per_session(monkeypatch):
    spawn = AsyncMock(return_value=_fake_medic_proc([
        json.dumps({"type": "result", "subtype": "success"}),
    ]))
    monkeypatch.setattr(medic, "_spawn_medic_proc", spawn)
    monkeypatch.setattr(medic.session_manager, "get_session_state", lambda n: None)

    q: asyncio.Queue = asyncio.Queue()
    medic_active = asyncio.Event()

    # Pretend a medic is already running for this session.
    medic._active_medics.add("sess")
    await medic.run_medic("sess", q, medic_active, elapsed_s=190.0)

    # No spawn, no frames — it bailed out immediately.
    assert not spawn.called
    assert q.empty()
    assert medic.is_medic_active("sess")


# ─────────────────────────────────────────────
# 5. Medic tier fires and defers the hard cap
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_watchdog_medic_tier_defers_hard_cap(monkeypatch):
    monkeypatch.setattr(sr, "_WATCHDOG_HEARTBEAT_S", 0.05)
    monkeypatch.setattr(sr, "_WATCHDOG_MEDIC_S", 0.1)
    monkeypatch.setattr(sr, "_WATCHDOG_HARD_CAP_S", 0.2)

    q: asyncio.Queue = asyncio.Queue()
    activity_event = asyncio.Event()
    medic_active = asyncio.Event()
    medic_calls: list[float] = []
    interrupt_calls: list[bool] = []

    def medic_fn(elapsed_s: float) -> None:
        medic_calls.append(elapsed_s)
        medic_active.set()  # simulate a medic that takes a while

    def hard_interrupt() -> None:
        interrupt_calls.append(True)

    watchdog = asyncio.create_task(sr._watchdog_loop(
        "sess", q, activity_event,
        hard_interrupt_fn=hard_interrupt,
        medic_fn=medic_fn,
        medic_active=medic_active,
    ))

    # Past the hard-cap threshold, but the medic is still "running" → deferred.
    await asyncio.sleep(0.4)
    assert len(medic_calls) >= 1, "medic_fn must fire at the medic tier"
    assert len(interrupt_calls) == 0, "hard cap must be deferred while medic active"

    # Medic finishes → hard cap is now allowed to fire on the next tick.
    medic_active.clear()
    await asyncio.sleep(0.2)
    assert len(interrupt_calls) >= 1, "hard cap must fire once the medic clears"

    watchdog.cancel()
    try:
        await watchdog
    except asyncio.CancelledError:
        pass

    assert any(isinstance(f, AiError) for f in _drain(q))


def _drain(q: asyncio.Queue) -> list:
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


# ─────────────────────────────────────────────
# 6. Manual /medic trigger (composer command)
# ─────────────────────────────────────────────

def test_parse_command_target():
    from devscope_bridge.main import _parse_command_target
    assert _parse_command_target("/medic", "cur") == "cur"            # no arg → current
    assert _parse_command_target("/medic check", "cur") == "check"    # explicit target
    assert _parse_command_target("/medic bad name!", "cur") == "cur"  # invalid → fallback


def test_scan_commands_includes_medic_builtin(tmp_path):
    from devscope_bridge.commands_scanner import scan_commands
    cmds = scan_commands(project_root=tmp_path)
    medic_cmds = [c for c in cmds if c["name"] == "/medic"]
    assert len(medic_cmds) == 1
    assert medic_cmds[0]["source"] == "builtin"


class _FakeWS:
    def __init__(self, frames):
        self._frames = list(frames)
        self.sent: list[str] = []

    async def receive_text(self):
        from fastapi import WebSocketDisconnect
        if self._frames:
            return self._frames.pop(0)
        raise WebSocketDisconnect()

    async def send_text(self, text: str):
        self.sent.append(text)


@pytest.mark.asyncio
async def test_ws_medic_command_triggers_medic(monkeypatch):
    import devscope_bridge.main as bridge_main

    calls: list[str] = []

    async def fake_run_medic(target, q, ev, elapsed_s=0.0, trigger="auto"):
        calls.append(target)

    monkeypatch.setattr(bridge_main.watchdog_medic, "run_medic", fake_run_medic)

    ws = _FakeWS([json.dumps({"type": "user_msg", "text": "/medic check"})])
    await bridge_main._ws_receive_loop(ws, "conversation")
    await asyncio.sleep(0.05)  # let the scheduled medic task run

    assert calls == ["check"], "/medic <target> must dispatch the medic on that session"
