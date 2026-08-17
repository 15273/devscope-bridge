"""
test_persistent_session.py

Tests for the persistent Claude process architecture:

1. Two sequential messages reuse the same process (no second spawn).
2. Mode change respawns the process (with --resume so context survives).
3. Model change respawns the process.
4. Unexpected process exit triggers AiError on the queue.
5. Per-turn AiDone/AiChunk frames are emitted correctly based on the
   stream-json result event.
6. Stdin message is encoded with the correct JSON envelope.
"""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call

import devscope_bridge.session_store as store
import devscope_bridge.session_manager as mgr
from devscope_bridge.models import AiChunk, AiDone, AiError, SessionReady


# ─────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────

@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "SESSIONS_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(store, "BRIDGE_DIR", tmp_path)
    mgr._sessions.clear()
    yield
    mgr._sessions.clear()


class _FakeAsyncIterator:
    """Async iterator that yields pre-encoded lines, mimicking asyncio stdout."""

    def __init__(self, lines: list[str]):
        self._items = [(line + "\n").encode("utf-8") for line in lines]
        self._idx = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._idx >= len(self._items):
            raise StopAsyncIteration
        item = self._items[self._idx]
        self._idx += 1
        return item


def _make_fake_proc(stdout_lines: list[str] | None = None):
    """Return a mock asyncio.subprocess.Process.

    stdout_lines: list of raw JSON strings to yield from stdout.
    If None, stdout yields nothing (empty turn).
    """
    proc = MagicMock()
    proc.pid = 99999
    proc.returncode = None  # alive

    proc.stdout = _FakeAsyncIterator(list(stdout_lines or []))

    proc.stderr = AsyncMock()
    proc.stderr.read = AsyncMock(return_value=b"")

    async def _wait():
        return 0

    proc.wait = _wait

    proc.stdin = MagicMock()
    proc.stdin.write = MagicMock()
    proc.stdin.drain = AsyncMock()

    return proc


def _init_event(session_id: str = "test-sid-0001") -> str:
    return json.dumps({"type": "system", "subtype": "init", "session_id": session_id})


def _chunk_event(text: str, session_id: str = "test-sid-0001") -> str:
    return json.dumps({
        "type": "stream_event",
        "session_id": session_id,
        "event": {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}},
    })


def _result_event(result: str = "ok", session_id: str = "test-sid-0001") -> str:
    return json.dumps({
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": result,
        "session_id": session_id,
    })


async def _drain_queue(q: asyncio.Queue, timeout: float = 3.0) -> list:
    """Drain queue until AiDone or AiError, or timeout."""
    frames = []
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


# ─────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_two_messages_reuse_one_process():
    """Second message does NOT spawn a new process — reuses the existing one."""
    spawn_count = 0
    proc = _make_fake_proc([
        _init_event(),
        _chunk_event("hello"),
        _result_event("hello"),
    ])

    async def fake_spawn(*args, **kwargs):
        nonlocal spawn_count
        spawn_count += 1
        return proc

    with patch("devscope_bridge.session_manager.asyncio.create_subprocess_exec",
               side_effect=fake_spawn):
        # First message — spawns
        q1 = await mgr.run_prompt("sess", "first message")
        await _drain_queue(q1)

        assert spawn_count == 1

        # Second message — must NOT spawn again
        q2 = await mgr.run_prompt("sess", "second message")

    assert spawn_count == 1, f"Expected 1 spawn, got {spawn_count}"

    # Both calls return the same queue object
    assert q1 is q2

    # stdin.write was called twice (once per message)
    assert proc.stdin.write.call_count == 2


@pytest.mark.asyncio
async def test_mode_change_respawns_with_resume():
    """Changing mode terminates the old process and spawns a new one with --resume."""
    sid = "orig-session-id"
    store.upsert_session("sess-mode", sid)

    spawned_args: list[list[str]] = []

    proc_act = _make_fake_proc([_init_event(sid), _result_event()])
    proc_plan = _make_fake_proc([_init_event(sid), _result_event()])

    async def fake_spawn(*args, **kwargs):
        spawned_args.append(list(args))
        return proc_act if len(spawned_args) == 1 else proc_plan

    with patch("devscope_bridge.session_manager.asyncio.create_subprocess_exec",
               side_effect=fake_spawn):
        # First message with mode=act
        q1 = await mgr.run_prompt("sess-mode", "msg1", mode="act")
        await _drain_queue(q1)

        # Second message with mode=plan — should respawn
        q2 = await mgr.run_prompt("sess-mode", "msg2", mode="plan")

    assert len(spawned_args) == 2, f"Expected 2 spawns, got {len(spawned_args)}"

    # Second spawn must include --resume with the stored session_id
    second_argv = spawned_args[1]
    assert "--resume" in second_argv
    resume_idx = second_argv.index("--resume")
    assert second_argv[resume_idx + 1] == sid

    # Second spawn must include plan mode args
    assert "--permission-mode" in second_argv
    plan_idx = second_argv.index("--permission-mode")
    assert second_argv[plan_idx + 1] == "plan"


@pytest.mark.asyncio
async def test_model_change_respawns():
    """Changing model also triggers a respawn."""
    spawned = 0

    proc1 = _make_fake_proc([_init_event(), _result_event()])
    proc2 = _make_fake_proc([_init_event(), _result_event()])

    async def fake_spawn(*args, **kwargs):
        nonlocal spawned
        spawned += 1
        return proc1 if spawned == 1 else proc2

    with patch("devscope_bridge.session_manager.asyncio.create_subprocess_exec",
               side_effect=fake_spawn):
        q1 = await mgr.run_prompt("sess-model", "msg1", model="claude-sonnet-4-5")
        await _drain_queue(q1)

        q2 = await mgr.run_prompt("sess-model", "msg2", model="claude-opus-4-5")
        await _drain_queue(q2)

    assert spawned == 2


@pytest.mark.asyncio
async def test_same_mode_and_model_no_respawn():
    """Same mode and model: only one spawn even across multiple messages."""
    spawned = 0
    proc = _make_fake_proc([_init_event(), _chunk_event("A"), _result_event("A")])

    async def fake_spawn(*args, **kwargs):
        nonlocal spawned
        spawned += 1
        return proc

    with patch("devscope_bridge.session_manager.asyncio.create_subprocess_exec",
               side_effect=fake_spawn):
        q = await mgr.run_prompt("sess-same", "msg1", mode="act", model="claude-sonnet-4-5")
        await _drain_queue(q)
        q2 = await mgr.run_prompt("sess-same", "msg2", mode="act", model="claude-sonnet-4-5")

    assert spawned == 1
    assert q is q2


@pytest.mark.asyncio
async def test_chunks_and_done_emitted_per_turn():
    """AiChunk and AiDone are emitted correctly for a turn with text output."""
    proc = _make_fake_proc([
        _init_event(),
        _chunk_event("Hello"),
        _chunk_event(" world"),
        _result_event("Hello world"),
    ])

    async def fake_spawn(*args, **kwargs):
        return proc

    with patch("devscope_bridge.session_manager.asyncio.create_subprocess_exec",
               side_effect=fake_spawn):
        q = await mgr.run_prompt("sess-emit", "say hello")
        frames = await _drain_queue(q)

    types = [type(f) for f in frames]
    assert SessionReady in types, f"Missing SessionReady: {types}"
    chunks = [f for f in frames if isinstance(f, AiChunk)]
    assert len(chunks) == 2
    assert chunks[0].text == "Hello"
    assert chunks[1].text == " world"
    assert any(isinstance(f, AiDone) for f in frames)
    assert not any(isinstance(f, AiError) for f in frames)


@pytest.mark.asyncio
async def test_unexpected_process_exit_emits_ai_error():
    """If the process exits without a result event, AiError is emitted."""
    # stdout yields nothing — the async for loop ends immediately (process exited)
    proc = _make_fake_proc([])  # empty stdout

    async def fake_spawn(*args, **kwargs):
        return proc

    with patch("devscope_bridge.session_manager.asyncio.create_subprocess_exec",
               side_effect=fake_spawn):
        q = await mgr.run_prompt("sess-exit", "hello")
        frames = await _drain_queue(q, timeout=3.0)

    errors = [f for f in frames if isinstance(f, AiError)]
    assert len(errors) == 1, f"Expected AiError, got {[type(f).__name__ for f in frames]}"


@pytest.mark.asyncio
async def test_stdin_message_json_envelope():
    """The message written to stdin has the correct stream-json envelope."""
    proc = _make_fake_proc([_init_event(), _result_event()])

    async def fake_spawn(*args, **kwargs):
        return proc

    with patch("devscope_bridge.session_manager.asyncio.create_subprocess_exec",
               side_effect=fake_spawn):
        await mgr.run_prompt("sess-stdin", "say HELLO")

    # stdin.write should have been called once
    assert proc.stdin.write.called
    raw_bytes: bytes = proc.stdin.write.call_args[0][0]
    payload = json.loads(raw_bytes.decode("utf-8").strip())

    assert payload["type"] == "user"
    assert payload["message"]["role"] == "user"
    content = payload["message"]["content"]
    assert isinstance(content, list)
    assert content[0]["type"] == "text"
    assert content[0]["text"] == "say HELLO"


@pytest.mark.asyncio
async def test_second_turn_does_not_emit_duplicate_session_ready():
    """On the second message, the repeated system/init event must NOT emit SessionReady."""
    sid = "shared-session"

    # Both turns get a system/init (as observed empirically).
    # We feed two complete turns sequentially via the same stdout.
    turn1_lines = [_init_event(sid), _chunk_event("T1", sid), _result_event("T1", sid)]
    turn2_lines = [_init_event(sid), _chunk_event("T2", sid), _result_event("T2", sid)]
    all_lines = turn1_lines + turn2_lines

    proc = _make_fake_proc(all_lines)
    results: list = []

    async def fake_spawn(*args, **kwargs):
        return proc

    with patch("devscope_bridge.session_manager.asyncio.create_subprocess_exec",
               side_effect=fake_spawn):
        # Turn 1 — drain until first AiDone
        q = await mgr.run_prompt("sess-init", "msg1")
        t1_frames = await _drain_queue(q)
        results.extend(t1_frames)

        # Turn 2 — same queue, drain until second AiDone
        # (no new spawn — same queue returned)
        q2 = await mgr.run_prompt("sess-init", "msg2")
        t2_frames = await _drain_queue(q2)
        results.extend(t2_frames)

    session_ready_count = sum(1 for f in results if isinstance(f, SessionReady))
    assert session_ready_count == 1, (
        f"Expected exactly 1 SessionReady (first turn only), got {session_ready_count}. "
        f"Frames: {[type(f).__name__ for f in results]}"
    )

    chunks = [f for f in results if isinstance(f, AiChunk)]
    assert len(chunks) == 2
    done_count = sum(1 for f in results if isinstance(f, AiDone))
    assert done_count == 2
