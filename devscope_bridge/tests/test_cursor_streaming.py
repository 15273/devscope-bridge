"""
test_cursor_streaming.py

Tests for the rewritten session_manager_cursor module:

1. Binary resolution: shutil.which, ~/.local/bin fallback, absent → AiError.
2. Streaming: --output-format stream-json lines become individual AiChunk frames.
3. Non-JSON lines are treated as plain-text chunks (legacy binary fallback).
4. result-event lines emit a final chunk.
5. Empty stdout: no AiChunk, but AiDone still emitted.
6. Non-zero exit emits AiError (no AiDone).
7. FileNotFoundError propagates as AiError with no SessionReady.
8. Session-id extraction from a JSON {"type":"session","id":"..."} line.
9. --resume is passed when prior_session_id is set.
10. --model is passed when model kwarg is given.
11. Legacy cursor.app binary: uses "agent" sub-command, no stream-json flag.
"""

import asyncio
import json
import os
import sys
import time
from datetime import datetime
import pytest
from unittest.mock import MagicMock, patch

import devscope_bridge.session_store as store
from devscope_bridge import cursor_watchdog
from devscope_bridge import session_manager_cursor as cursor_mod
from devscope_bridge.models import AiChunk, AiDone, AiError, SessionReady


# ─────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────

@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "SESSIONS_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(store, "BRIDGE_DIR", tmp_path)


async def _drain(q: asyncio.Queue, timeout: float = 3.0) -> list:
    """Collect frames until AiDone or AiError, then return all."""
    frames: list = []
    try:
        async with asyncio.timeout(timeout):
            while True:
                frame = await q.get()
                frames.append(frame)
                if isinstance(frame, (AiDone, AiError)):
                    break
    except TimeoutError:
        pass
    return frames


def _make_fake_blocking(returncode: int, stdout_lines: list[str], stderr: str = ""):
    """Patch _run_cursor_streaming_blocking with deterministic stdout lines."""
    from devscope_bridge.models import TurnState

    def _inner(prompt, prior, cwd, mode, model, loop, q, session_name):
        sid = prior or "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        asyncio.run_coroutine_threadsafe(
            q.put(SessionReady(session=session_name, session_id=sid, resumed=bool(prior))),
            loop,
        ).result(timeout=2)
        accum = ""
        emitted = False
        for line in stdout_lines:
            delta, accum, _ = cursor_mod._parse_line_to_delta(line, accum)
            if delta:
                asyncio.run_coroutine_threadsafe(
                    q.put(AiChunk(session=session_name, text=delta)),
                    loop,
                ).result(timeout=2)
                emitted = True
        if returncode != 0:
            asyncio.run_coroutine_threadsafe(
                q.put(AiError(session=session_name, exit_code=returncode, stderr_tail=stderr)),
                loop,
            ).result(timeout=2)
            asyncio.run_coroutine_threadsafe(
                q.put(TurnState(session=session_name, running=False)),
                loop,
            ).result(timeout=2)
            return
        if not emitted and stdout_lines:
            raw = "\n".join(stdout_lines).strip()
            if raw:
                asyncio.run_coroutine_threadsafe(
                    q.put(AiChunk(session=session_name, text=raw)),
                    loop,
                ).result(timeout=2)
        asyncio.run_coroutine_threadsafe(
            q.put(AiDone(session=session_name, exit_code=0)),
            loop,
        ).result(timeout=2)
        asyncio.run_coroutine_threadsafe(
            q.put(TurnState(session=session_name, running=False)),
            loop,
        ).result(timeout=2)

    return _inner


# ─────────────────────────────────────────────
# Binary resolution tests
# ─────────────────────────────────────────────

def test_resolve_cursor_bin_uses_env_var(monkeypatch, tmp_path):
    fake_bin = tmp_path / "fake-cursor-agent"
    fake_bin.touch()
    monkeypatch.setenv("CURSOR_BIN", str(fake_bin))
    result = cursor_mod._resolve_cursor_bin()
    assert result == str(fake_bin)


def test_resolve_cursor_bin_env_var_missing_file(monkeypatch):
    monkeypatch.setenv("CURSOR_BIN", "/no/such/binary")
    result = cursor_mod._resolve_cursor_bin()
    assert result is None


def test_resolve_cursor_bin_uses_which(monkeypatch, tmp_path):
    monkeypatch.delenv("CURSOR_BIN", raising=False)
    fake_bin = tmp_path / "cursor-agent"
    fake_bin.touch()
    with patch("shutil.which", return_value=str(fake_bin)):
        result = cursor_mod._resolve_cursor_bin()
    assert result == str(fake_bin)


def test_resolve_cursor_bin_falls_back_to_local_bin(monkeypatch, tmp_path):
    monkeypatch.delenv("CURSOR_BIN", raising=False)
    fake_local = tmp_path / "cursor-agent"
    fake_local.touch()
    with patch("shutil.which", return_value=None):
        with patch.object(cursor_mod, "_LOCAL_BIN", str(fake_local)):
            result = cursor_mod._resolve_cursor_bin()
    assert result == str(fake_local)


def test_resolve_cursor_bin_falls_back_to_cursor_app(monkeypatch, tmp_path):
    monkeypatch.delenv("CURSOR_BIN", raising=False)
    fake_app = tmp_path / "cursor"
    fake_app.touch()
    with patch("shutil.which", return_value=None):
        with patch.object(cursor_mod, "_LOCAL_BIN", "/no/such/local"):
            with patch.object(cursor_mod, "_CURSOR_APP_BIN", str(fake_app)):
                result = cursor_mod._resolve_cursor_bin()
    assert result == str(fake_app)


def test_resolve_cursor_bin_returns_none_when_absent(monkeypatch):
    monkeypatch.delenv("CURSOR_BIN", raising=False)
    with patch("shutil.which", return_value=None):
        with patch.object(cursor_mod, "_LOCAL_BIN", "/no/such"):
            with patch.object(cursor_mod, "_CURSOR_APP_BIN", "/no/such"):
                result = cursor_mod._resolve_cursor_bin()
    assert result is None


# ─────────────────────────────────────────────
# Chunk parsing tests
# ─────────────────────────────────────────────

def test_parse_chunk_text_delta():
    line = json.dumps({"type": "text_delta", "text": "Hello"})
    assert cursor_mod._parse_chunk_from_event(line) == "Hello"


def test_parse_chunk_content_event():
    line = json.dumps({"type": "content", "text": "World"})
    assert cursor_mod._parse_chunk_from_event(line) == "World"


def test_parse_chunk_result_event():
    line = json.dumps({"type": "result", "output": "Final answer"})
    assert cursor_mod._parse_chunk_from_event(line) == "Final answer"


def test_parse_chunk_result_event_cursor_agent_result_key():
    line = json.dumps({"type": "result", "subtype": "success", "result": "Final answer"})
    assert cursor_mod._parse_chunk_from_event(line) == "Final answer"


def test_parse_chunk_cursor_agent_assistant_delta():
    line = json.dumps({
        "type": "assistant",
        "message": {"role": "assistant", "content": [{"type": "text", "text": "Hello"}]},
        "session_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    })
    assert cursor_mod._parse_chunk_from_event(line) == "Hello"


def test_parse_line_to_delta_accumulates_assistant_cumulative():
    line1 = json.dumps({
        "type": "assistant",
        "message": {"role": "assistant", "content": [{"type": "text", "text": "Hi"}]},
    })
    line2 = json.dumps({
        "type": "assistant",
        "message": {"role": "assistant", "content": [{"type": "text", "text": "Hi there"}]},
    })
    d1, acc1, _ = cursor_mod._parse_line_to_delta(line1, "")
    d2, acc2, _ = cursor_mod._parse_line_to_delta(line2, acc1)
    assert d1 == "Hi"
    assert d2 == " there"
    assert acc2 == "Hi there"


def test_parse_chunk_non_json_plain_text():
    """Non-JSON lines are returned as plain text (legacy binary)."""
    assert cursor_mod._parse_chunk_from_event("Just plain text") == "Just plain text"


def test_parse_chunk_empty_line():
    assert cursor_mod._parse_chunk_from_event("") is None
    assert cursor_mod._parse_chunk_from_event("   ") is None


def test_parse_chunk_unrecognised_json_event():
    """Unknown event types yield None — we only chunk known types."""
    line = json.dumps({"type": "heartbeat", "ts": 12345})
    assert cursor_mod._parse_chunk_from_event(line) is None


# ─────────────────────────────────────────────
# Session-id extraction tests
# ─────────────────────────────────────────────

def test_extract_session_id_from_json_event():
    sid = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
    lines = [json.dumps({"type": "session", "id": sid}), "some output"]
    assert cursor_mod._extract_session_id_from_lines(lines) == sid


def test_extract_session_id_from_cursor_system_init():
    sid = "e0ea0c6e-30ed-4dd5-9cbf-500023d6e452"
    lines = [
        json.dumps({
            "type": "system",
            "subtype": "init",
            "session_id": sid,
            "model": "Sonnet 4",
        }),
    ]
    assert cursor_mod._extract_session_id_from_lines(lines) == sid


def test_extract_session_id_from_bare_uuid_first_line():
    sid = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
    lines = [sid, "output line"]
    assert cursor_mod._extract_session_id_from_lines(lines) == sid


def test_extract_session_id_returns_none_when_absent():
    lines = [json.dumps({"type": "text_delta", "text": "hi"}), "no uuid here"]
    assert cursor_mod._extract_session_id_from_lines(lines) is None


def test_extract_session_id_skips_empty_lines():
    sid = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
    lines = ["", "  ", sid]
    assert cursor_mod._extract_session_id_from_lines(lines) == sid


# ─────────────────────────────────────────────
# Argument builder tests
# ─────────────────────────────────────────────

def test_build_cursor_args_standalone_uses_stream_json():
    cmd = cursor_mod._build_cursor_args(
        "/home/user/.local/bin/cursor-agent",
        "hello",
        prior_session_id=None,
        mode="act",
        model=None,
        workspace="/repo",
    )
    assert "--output-format" in cmd
    idx = cmd.index("--output-format")
    assert cmd[idx + 1] == "stream-json"
    assert "--stream-partial-output" in cmd
    assert "--print" in cmd
    assert "--trust" in cmd
    assert "--approve-mcps" in cmd
    assert "--force" in cmd
    assert "--workspace" in cmd
    widx = cmd.index("--workspace")
    assert cmd[widx + 1] == "/repo"
    # The prompt is the last element; act mode prepends a system suffix so
    # the last arg contains "hello" rather than being exactly "hello".
    assert "hello" in cmd[-1]


def test_build_cursor_args_resume_flag():
    cmd = cursor_mod._build_cursor_args(
        "/home/user/.local/bin/cursor-agent",
        "hello",
        prior_session_id="abc-123-uuid-here-0000",
        mode="act",
        model=None,
    )
    assert "--resume" in cmd
    idx = cmd.index("--resume")
    assert cmd[idx + 1] == "abc-123-uuid-here-0000"


def test_build_cursor_args_model_flag():
    cmd = cursor_mod._build_cursor_args(
        "/home/user/.local/bin/cursor-agent",
        "hello",
        prior_session_id=None,
        mode="act",
        model="gpt-5",
    )
    assert "--model" in cmd
    idx = cmd.index("--model")
    assert cmd[idx + 1] == "gpt-5"


def test_build_cursor_args_plan_mode():
    cmd = cursor_mod._build_cursor_args(
        "/home/user/.local/bin/cursor-agent",
        "hello",
        prior_session_id=None,
        mode="plan",
        model=None,
    )
    assert "--mode" in cmd
    idx = cmd.index("--mode")
    assert cmd[idx + 1] == "plan"


def test_build_cursor_args_legacy_cursor_app_uses_agent_subcommand():
    """Legacy Cursor.app binary uses 'agent' subcommand with same flags as standalone."""
    cmd = cursor_mod._build_cursor_args(
        "/Applications/Cursor.app/Contents/Resources/app/bin/cursor",
        "hello",
        prior_session_id=None,
        mode="act",
        model=None,
        workspace="/repo",
    )
    assert cmd[1] == "agent", f"Expected 'agent' subcommand, got: {cmd}"
    assert "--output-format" in cmd
    assert "--approve-mcps" in cmd
    assert "--workspace" in cmd
    assert "/repo" in cmd


# ─────────────────────────────────────────────
# dispatch_cursor integration tests (mock _run_cursor_streaming)
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_streaming_lines_become_individual_chunks():
    lines = [
        json.dumps({"type": "text_delta", "text": "Hello"}),
        json.dumps({"type": "text_delta", "text": " world"}),
        json.dumps({"type": "result", "output": "!"}),
    ]
    with patch.object(cursor_mod, "_run_cursor_streaming_blocking", side_effect=_make_fake_blocking(0, lines)):
        q = await cursor_mod.dispatch_cursor("sess", "prompt", None, "/tmp")
        frames = await _drain(q)

    chunks = [f for f in frames if isinstance(f, AiChunk)]
    assert len(chunks) == 3
    assert chunks[0].text == "Hello"
    assert chunks[1].text == " world"
    assert chunks[2].text == "!"
    assert any(isinstance(f, AiDone) for f in frames)
    assert not any(isinstance(f, AiError) for f in frames)


@pytest.mark.asyncio
async def test_session_ready_emitted_before_chunks():
    lines = [json.dumps({"type": "text_delta", "text": "hi"})]
    with patch.object(cursor_mod, "_run_cursor_streaming_blocking", side_effect=_make_fake_blocking(0, lines)):
        q = await cursor_mod.dispatch_cursor("sess2", "hi", None, "/tmp")
        frames = await _drain(q)

    ready_idx = next(i for i, f in enumerate(frames) if isinstance(f, SessionReady))
    chunk_idx = next(i for i, f in enumerate(frames) if isinstance(f, AiChunk))
    assert ready_idx < chunk_idx, "SessionReady must precede first AiChunk"


@pytest.mark.asyncio
async def test_nonzero_exit_emits_error_not_done():
    with patch.object(
        cursor_mod, "_run_cursor_streaming_blocking",
        side_effect=_make_fake_blocking(1, [], "something broke"),
    ):
        q = await cursor_mod.dispatch_cursor("sess3", "bad", None, "/tmp")
        frames = await _drain(q)

    assert any(isinstance(f, AiError) for f in frames)
    assert not any(isinstance(f, AiDone) for f in frames)
    error = next(f for f in frames if isinstance(f, AiError))
    assert error.exit_code == 1


@pytest.mark.asyncio
async def test_binary_absent_emits_error_no_session_ready():
    def _raise(prompt, prior, cwd, mode, model, loop, q, session_name):
        raise FileNotFoundError("cursor-agent not found")

    with patch.object(cursor_mod, "_run_cursor_streaming_blocking", side_effect=_raise):
        q = await cursor_mod.dispatch_cursor("sess4", "hi", None, "/tmp")
        frames = await _drain(q)

    assert not any(isinstance(f, SessionReady) for f in frames)
    errors = [f for f in frames if isinstance(f, AiError)]
    assert len(errors) == 1
    assert "not found" in errors[0].stderr_tail.lower() or "cursor" in errors[0].stderr_tail.lower()


@pytest.mark.asyncio
async def test_empty_stdout_emits_done_no_chunk():
    with patch.object(cursor_mod, "_run_cursor_streaming_blocking", side_effect=_make_fake_blocking(0, [])):
        q = await cursor_mod.dispatch_cursor("sess5", "quiet", None, "/tmp")
        frames = await _drain(q)

    assert not any(isinstance(f, AiChunk) for f in frames)
    assert any(isinstance(f, AiDone) for f in frames)


@pytest.mark.asyncio
async def test_plain_text_lines_emitted_as_fallback_chunk():
    """When all stdout lines are non-JSON (legacy cursor), join as one chunk."""
    lines = ["Part one.", "Part two."]
    with patch.object(cursor_mod, "_run_cursor_streaming_blocking", side_effect=_make_fake_blocking(0, lines)):
        q = await cursor_mod.dispatch_cursor("sess6", "legacy", None, "/tmp")
        frames = await _drain(q)

    chunks = [f for f in frames if isinstance(f, AiChunk)]
    # Each plain-text line parsed individually
    assert len(chunks) >= 1
    all_text = "".join(c.text for c in chunks)
    assert "Part one." in all_text
    assert "Part two." in all_text


@pytest.mark.asyncio
async def test_resume_stored_session_id():
    """When prior_session_id is set, it is passed through and preserved."""
    prior_sid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    store.upsert_session("sess7", prior_sid)

    captured_prior: list = []

    def _capture(prompt, prior, cwd, mode, model, loop, q, session_name):
        captured_prior.append(prior)
        _make_fake_blocking(0, [])(prompt, prior, cwd, mode, model, loop, q, session_name)

    with patch.object(cursor_mod, "_run_cursor_streaming_blocking", side_effect=_capture):
        stored = store.get_session("sess7")
        prior = stored["session_id"] if stored else None
        q = await cursor_mod.dispatch_cursor("sess7", "hi", prior, "/tmp")
        await _drain(q)

    assert captured_prior[0] == prior_sid


@pytest.mark.asyncio
async def test_model_kwarg_passed_through():
    """The model kwarg is forwarded to _run_cursor_streaming."""
    captured: dict = {}

    def _capture(prompt, prior, cwd, mode, model, loop, q, session_name):
        captured["model"] = model
        _make_fake_blocking(0, [])(prompt, prior, cwd, mode, model, loop, q, session_name)

    with patch.object(cursor_mod, "_run_cursor_streaming_blocking", side_effect=_capture):
        q = await cursor_mod.dispatch_cursor("sess8", "hi", None, "/tmp", model="gpt-5")
        await _drain(q)

    assert captured.get("model") == "gpt-5"


# ─────────────────────────────────────────────
# B1 — real streaming (the missing-yield regression test)
#
# Everything above mocks `_run_cursor_streaming_blocking` wholesale, so it
# never exercised the real `_iter_stdout_lines` generator. These tests spawn
# an actual fake "cursor-agent" subprocess and call the REAL function.
# ─────────────────────────────────────────────

def _write_fake_cursor_agent(tmp_path, body: str):
    """Write an executable fake cursor-agent binary running under this venv's
    interpreter (so it works regardless of a bare `python3` on PATH)."""
    script = tmp_path / "cursor-agent"
    script.write_text(f"#!{sys.executable}\n{body}")
    script.chmod(0o755)
    return script


@pytest.mark.asyncio
async def test_real_streaming_emits_chunks_before_process_exit(tmp_path):
    """Regression test for the missing `yield` (B1): the old
    `_iter_stdout_lines` collected every line into a list and returned only
    after the process exited, so all frames arrived in one post-mortem burst.
    With true streaming, the first frame lands soon after the child's first
    print — well before the (artificially slow) process actually exits."""
    script = _write_fake_cursor_agent(
        tmp_path,
        "import json, time\n"
        "print(json.dumps({'type': 'text_delta', 'text': 'Hello'}), flush=True)\n"
        "time.sleep(0.5)\n"
        "print(json.dumps({'type': 'text_delta', 'text': ' world'}), flush=True)\n"
        "time.sleep(0.5)\n"
        "print(json.dumps({'type': 'result', 'output': '!'}), flush=True)\n",
    )

    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue()
    arrival_times: list[float] = []

    async def _collector():
        while True:
            frame = await q.get()
            arrival_times.append(time.monotonic())
            if isinstance(frame, (AiDone, AiError)):
                break

    collector = asyncio.create_task(_collector())
    start = time.monotonic()
    with patch.object(cursor_mod, "_resolve_cursor_bin", return_value=str(script)):
        await asyncio.to_thread(
            cursor_mod._run_cursor_streaming_blocking,
            "prompt", None, str(tmp_path), None, None, loop, q, "real_stream_sess",
        )
    await asyncio.wait_for(collector, timeout=5.0)
    total_elapsed = time.monotonic() - start

    assert len(arrival_times) >= 2
    assert arrival_times[0] < start + (total_elapsed - 0.3), (
        "first frame should arrive well before process exit, not in a "
        "post-mortem burst"
    )


@pytest.mark.asyncio
async def test_stderr_drain_prevents_deadlock_on_large_output(tmp_path):
    """B2: a child writing well over the ~64KB pipe buffer to stderr before
    exiting must not deadlock the turn (old code only read stderr after
    proc.wait(), which never returns while the child blocks on a full pipe)."""
    script = _write_fake_cursor_agent(
        tmp_path,
        "import sys, json\n"
        "sys.stderr.write('x' * 200000 + chr(10))\n"
        "sys.stderr.flush()\n"
        "print(json.dumps({'type': 'result', 'output': 'done'}), flush=True)\n",
    )

    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue()
    with patch.object(cursor_mod, "_resolve_cursor_bin", return_value=str(script)):
        await asyncio.wait_for(
            asyncio.to_thread(
                cursor_mod._run_cursor_streaming_blocking,
                "prompt", None, str(tmp_path), None, None, loop, q, "stderr_drain_sess",
            ),
            timeout=5.0,
        )

    frames = []
    while not q.empty():
        frames.append(q.get_nowait())
    assert any(isinstance(f, AiDone) for f in frames)


@pytest.mark.asyncio
async def test_real_empty_output_zero_exit_emits_ai_error(tmp_path):
    """B3: returncode 0 with truly empty stdout must not look like a clean
    success — it now emits AiError instead of a silent AiDone."""
    script = _write_fake_cursor_agent(tmp_path, "import sys\nsys.exit(0)\n")

    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue()
    with patch.object(cursor_mod, "_resolve_cursor_bin", return_value=str(script)):
        await asyncio.to_thread(
            cursor_mod._run_cursor_streaming_blocking,
            "prompt", None, str(tmp_path), None, None, loop, q, "empty_sess",
        )

    frames = []
    while not q.empty():
        frames.append(q.get_nowait())
    assert any(isinstance(f, AiError) for f in frames)
    assert not any(isinstance(f, AiDone) for f in frames)


@pytest.mark.asyncio
async def test_real_empty_output_zero_exit_includes_stderr_tail(tmp_path):
    script = _write_fake_cursor_agent(
        tmp_path,
        "import sys\nsys.stderr.write('auth failed\\n')\nsys.exit(0)\n",
    )
    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue()
    with patch.object(cursor_mod, "_resolve_cursor_bin", return_value=str(script)):
        await asyncio.to_thread(
            cursor_mod._run_cursor_streaming_blocking,
            "prompt", None, str(tmp_path), None, None, loop, q, "empty_sess2",
        )

    frames = []
    while not q.empty():
        frames.append(q.get_nowait())
    error = next(f for f in frames if isinstance(f, AiError))
    assert "auth failed" in error.stderr_tail


# ─────────────────────────────────────────────
# B4 — queue visibility + Stop that actually stops
# ─────────────────────────────────────────────

def test_queued_turns_visible_and_interrupt_drains_queue():
    name = "qsess_unit"
    out_q: asyncio.Queue = asyncio.Queue()
    turn_q: asyncio.Queue = asyncio.Queue()
    cursor_mod._cursor_out_queues[name] = out_q
    cursor_mod._cursor_turn_queues[name] = turn_q
    cursor_mod._cursor_running[name] = True  # a turn is "in flight"
    try:
        turn_q.put_nowait(cursor_mod._CursorTurn("second", None, "/tmp", None, None))
        turn_q.put_nowait(cursor_mod._CursorTurn("third", None, "/tmp", None, None))

        state = cursor_mod.get_session_state(name)
        assert state["queued_turns"] == 2

        result = cursor_mod.interrupt_cursor(name)
        assert result is True
        assert turn_q.empty()

        state_after = cursor_mod.get_session_state(name)
        assert state_after["queued_turns"] == 0

        activity = out_q.get_nowait()
        assert "cancelled" in activity.label
    finally:
        cursor_mod._cursor_out_queues.pop(name, None)
        cursor_mod._cursor_turn_queues.pop(name, None)
        cursor_mod._cursor_running.pop(name, None)


@pytest.mark.asyncio
async def test_dispatch_cursor_emits_queued_activity_when_busy(monkeypatch):
    name = "qsess_dispatch"
    monkeypatch.setattr(cursor_mod, "_ensure_cursor_worker", lambda n: None)
    cursor_mod._cursor_running[name] = True
    try:
        out_q = await cursor_mod.dispatch_cursor(name, "first while busy", None, "/tmp")
        frames = []
        while not out_q.empty():
            frames.append(out_q.get_nowait())
        activities = [f for f in frames if isinstance(f, cursor_mod.AgentActivity)]
        assert any("queued" in a.label and "1" in a.label for a in activities)

        state = cursor_mod.get_session_state(name)
        assert state["queued_turns"] == 1
        assert state["last_msg_at"] is not None
    finally:
        cursor_mod._cursor_running.pop(name, None)
        cursor_mod._cursor_turn_queues.pop(name, None)
        cursor_mod._cursor_out_queues.pop(name, None)
        cursor_mod._cursor_last_msg_at.pop(name, None)


# ─────────────────────────────────────────────
# B5 — honest cursor session state (contract 2 keys)
# ─────────────────────────────────────────────

def test_get_session_state_exposes_contract_2_keys():
    name = "state_sess"
    cursor_mod._cursor_running[name] = True
    cursor_mod._cursor_last_msg_at[name] = datetime.now()
    cursor_watchdog.begin_turn(name)
    cursor_watchdog.touch_stdout(name)
    cursor_watchdog.set_current_tool(name, "shell")
    try:
        state = cursor_mod.get_session_state(name)
        assert state is not None
        for key in (
            "last_msg_at", "last_output_at", "current_tool",
            "turn_elapsed_s", "queued_turns", "awaiting",
        ):
            assert key in state, f"missing contract-2 key: {key}"
        assert state["awaiting"] is None
        assert state["current_tool"] == "shell"
        assert isinstance(state["turn_elapsed_s"], float)
        assert isinstance(state["last_output_at"], float)
        assert state["last_msg_at"] is not None
        # last_msg_at must be isoformat-parseable — main.py's _silence_seconds
        # calls datetime.fromisoformat() on this exact field for Claude
        # sessions; cursor must be compatible the same way.
        datetime.fromisoformat(state["last_msg_at"])
    finally:
        cursor_watchdog.end_turn(name)
        cursor_mod._cursor_running.pop(name, None)
        cursor_mod._cursor_last_msg_at.pop(name, None)


def test_get_session_state_none_when_fully_idle():
    assert cursor_mod.get_session_state("no-such-session-at-all") is None


# ─────────────────────────────────────────────
# B6 — parser correctness (functions living in session_manager_cursor.py)
# ─────────────────────────────────────────────

def test_delta_from_cumulative_does_not_drop_legitimate_repeated_substring():
    """Old bug: `cumulative in accum` matched ANY substring occurrence
    anywhere in accum, so legitimately different/repeated text that merely
    happened to also appear earlier in accum was silently dropped."""
    accum = "please read the config file and then read the log file"
    cumulative = "read the log file"  # inside accum, but NOT a prefix of it
    delta, new_accum = cursor_mod._delta_from_cumulative(cumulative, accum)
    assert delta == cumulative
    assert new_accum == cumulative


def test_delta_from_cumulative_still_suppresses_true_shrink_back():
    accum = "Hello there"
    cumulative = "Hello"  # a genuine earlier state — accum starts with it
    delta, new_accum = cursor_mod._delta_from_cumulative(cumulative, accum)
    assert delta == ""
    assert new_accum == accum


def test_parse_line_to_delta_malformed_json_fragment_not_leaked_as_text():
    delta, _, _ = cursor_mod._parse_line_to_delta('{"type": "assistant", "mess', "")
    assert delta is None


def test_parse_line_to_delta_result_event_emits_content_beyond_accum():
    """Old bug: result text was discarded whenever accum was non-empty, even
    when it held genuinely different/additional content."""
    line = json.dumps({"type": "result", "output": "different final text"})
    delta, new_accum, _ = cursor_mod._parse_line_to_delta(line, "streamed so far")
    assert delta == "different final text"
    assert new_accum == "streamed so fardifferent final text"


def test_parse_line_to_delta_result_event_suppressed_when_prefix_of_accum():
    line = json.dumps({"type": "result", "output": "streamed"})
    delta, new_accum, _ = cursor_mod._parse_line_to_delta(line, "streamed so far")
    assert delta is None
    assert new_accum == "streamed so far"
