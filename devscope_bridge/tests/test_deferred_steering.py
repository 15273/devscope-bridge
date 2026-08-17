"""
test_deferred_steering.py — FIX 3: a message arriving mid-turn while Task/Agent
sub-agents are in flight must NOT be written to stdin (the CLI treats mid-turn
stdin as an interrupt, killing the sub-agents). It is queued on the active
session and flushed as a fresh turn at turn end.

Coverage
--------
1. run_prompt mid-turn + sub-agents in flight → queued, no stdin write, a
   queue-notice frame is emitted, pending_prompts untouched.
2. run_prompt mid-turn WITHOUT sub-agents keeps the A8 steering write-through.
3. flush_deferred_message sends exactly ONE deferred message as a new turn.
4. flush drops the queue with no write when the process died/respawned.
5. continuous_reader triggers the flush at normal turn end (result event).
"""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock

import devscope_bridge.session_manager as mgr
import devscope_bridge.session_reader as sr
import devscope_bridge.session_store as store
from devscope_bridge.models import AgentActivity, TurnState


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "SESSIONS_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(store, "BRIDGE_DIR", tmp_path)
    mgr._sessions.clear()
    mgr._out_queues.clear()
    yield
    mgr._sessions.clear()
    mgr._out_queues.clear()


class _RecordingStdin:
    def __init__(self):
        self.writes: list[bytes] = []

    def write(self, b: bytes) -> None:
        self.writes.append(b)

    async def drain(self) -> None:
        return None


class _FakeProc:
    def __init__(self, pid: int = 555):
        self.pid = pid
        self.returncode = None
        self.stdin = _RecordingStdin()


def _install_fake_spawn(monkeypatch, proc):
    async def fake_spawn(*args, **kwargs):
        return proc

    async def fake_reader(*args, **kwargs):
        await asyncio.sleep(999)

    monkeypatch.setattr(mgr, "_spawn_claude_proc", fake_spawn)
    monkeypatch.setattr(mgr.session_reader, "continuous_reader", fake_reader)


def _drain(q: asyncio.Queue) -> list:
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


def _make_active(name: str, proc, *, deferred=None, deferred_pid=None) -> "mgr._ActiveSession":
    turn_done = asyncio.Event()
    turn_done.set()
    active = mgr._ActiveSession(
        name=name, session_id="sid", proc=proc,
        out_queue=asyncio.Queue(), reader_task=None, idle_task=None,
        mode=None, model=None, turn_done=turn_done,
        deferred_messages=list(deferred or []), deferred_pid=deferred_pid,
    )
    mgr._sessions[name] = active
    return active


# ─────────────────────────────────────────────
# 1–2. run_prompt: queue vs steer
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_prompt_queues_instead_of_steering_with_subagents(monkeypatch):
    proc = _FakeProc()
    _install_fake_spawn(monkeypatch, proc)
    monkeypatch.setattr(mgr.sub_agent_tracker, "has_in_flight", lambda _n: False)

    q = await mgr.run_prompt("defer-sess", "first message")
    active = mgr._sessions["defer-sess"]
    assert len(proc.stdin.writes) == 1

    # Turn now running (turn_done cleared) AND sub-agents in flight → queue.
    monkeypatch.setattr(mgr.sub_agent_tracker, "has_in_flight", lambda _n: True)
    q2 = await mgr.run_prompt("defer-sess", "second message mid-turn")
    assert q2 is q, "deferred dispatch must return the same stable out_queue"

    assert len(proc.stdin.writes) == 1, "deferred message must NOT be written to stdin"
    assert len(active.deferred_messages) == 1
    assert active.deferred_messages[0][0] == "second message mid-turn"
    assert active.deferred_pid == proc.pid
    assert active.pending_prompts == 0, "a queued message is not a steering write"
    assert not active.turn_done.is_set(), "the running turn must stay running"

    frames = _drain(q)
    notices = [
        f for f in frames
        if isinstance(f, AgentActivity) and "queued" in f.label.lower()
    ]
    assert len(notices) == 1, f"Expected one queue notice: {frames}"


@pytest.mark.asyncio
async def test_run_prompt_mid_turn_without_subagents_still_steers(monkeypatch):
    proc = _FakeProc()
    _install_fake_spawn(monkeypatch, proc)
    monkeypatch.setattr(mgr.sub_agent_tracker, "has_in_flight", lambda _n: False)

    await mgr.run_prompt("steer-sess", "first message")
    active = mgr._sessions["steer-sess"]
    await mgr.run_prompt("steer-sess", "second message mid-turn")

    assert len(proc.stdin.writes) == 2, "no sub-agents → steering keeps writing to stdin"
    assert active.pending_prompts == 1
    assert active.deferred_messages == []


# ─────────────────────────────────────────────
# 3–4. flush_deferred_message
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_flush_deferred_message_sends_exactly_one():
    proc = _FakeProc(pid=777)
    active = _make_active(
        "flush-sess", proc,
        deferred=[("msg one", []), ("msg two", [])], deferred_pid=777,
    )

    await mgr.flush_deferred_message("flush-sess")

    assert len(proc.stdin.writes) == 1, "exactly ONE deferred message per turn end"
    payload = json.loads(proc.stdin.writes[0].decode("utf-8"))
    assert payload["message"]["content"][-1]["text"] == "msg one"
    assert active.deferred_messages == [("msg two", [])]
    assert not active.turn_done.is_set(), "flush starts a new turn"
    assert active.turn_started_at is not None
    frames = _drain(active.out_queue)
    assert any(isinstance(f, TurnState) and f.running for f in frames)


@pytest.mark.asyncio
async def test_flush_drops_deferred_when_process_respawned():
    proc = _FakeProc(pid=888)  # pid differs from the one the defer was queued on
    active = _make_active(
        "flush-drop", proc, deferred=[("stale msg", [])], deferred_pid=777,
    )

    await mgr.flush_deferred_message("flush-drop")

    assert proc.stdin.writes == [], "must not write to a respawned process"
    assert active.deferred_messages == [], "queue dropped with a logged warning"
    assert active.turn_done.is_set(), "no new turn is started on drop"
    assert _drain(active.out_queue) == []


@pytest.mark.asyncio
async def test_flush_noop_without_session_or_deferred():
    await mgr.flush_deferred_message("no-such-session")  # must not raise
    proc = _FakeProc()
    active = _make_active("empty-sess", proc)
    await mgr.flush_deferred_message("empty-sess")
    assert proc.stdin.writes == []
    assert active.turn_done.is_set()


# ─────────────────────────────────────────────
# 5. continuous_reader flushes at normal turn end
# ─────────────────────────────────────────────

class _ControlledAsyncIterator:
    def __init__(self):
        self._q: asyncio.Queue = asyncio.Queue()

    def __aiter__(self):
        return self

    async def __anext__(self):
        item = await self._q.get()
        if item is None:
            raise StopAsyncIteration
        return item

    def push(self, obj: dict) -> None:
        self._q.put_nowait((json.dumps(obj) + "\n").encode("utf-8"))

    def close(self) -> None:
        self._q.put_nowait(None)


@pytest.mark.asyncio
async def test_turn_end_result_event_triggers_flush(monkeypatch):
    flushed: list[str] = []

    async def fake_flush(name: str) -> None:
        flushed.append(name)

    monkeypatch.setattr(mgr, "flush_deferred_message", fake_flush)

    proc = MagicMock()
    proc.pid = 999
    proc.returncode = None
    ctrl = _ControlledAsyncIterator()
    proc.stdout = ctrl
    proc.stdin = MagicMock()
    proc.stdin.drain = AsyncMock()

    async def _wait():
        return 0
    proc.wait = _wait

    turn_done = asyncio.Event()
    q: asyncio.Queue = asyncio.Queue()
    reader = asyncio.create_task(sr.continuous_reader("rd-flush", proc, q, turn_done))

    ctrl.push({
        "type": "result", "subtype": "success", "is_error": False,
        "result": "ok", "session_id": "s1", "usage": {},
        "total_cost_usd": 0, "duration_ms": 0,
    })
    await asyncio.sleep(0.1)
    ctrl.close()
    try:
        await asyncio.wait_for(reader, timeout=2.0)
    except asyncio.TimeoutError:
        reader.cancel()

    assert flushed == ["rd-flush"], "turn end must trigger flush_deferred_message"
    assert turn_done.is_set()
