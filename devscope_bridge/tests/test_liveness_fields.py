"""
test_liveness_fields.py — A3 (contract 2 liveness fields) + A5 (two separate
silence clocks: last_output_at vs last_user_msg_at).

Coverage
--------
1. session_manager.get_session_state exposes last_output_at, current_tool,
   turn_elapsed_s, queued_turns, awaiting alongside last_user_msg_at — and the
   two clocks are genuinely independent (last_user_msg_at can be "old" while
   last_output_at is fresh, and vice versa).
2. session_reader.touch_output / get_last_output_at round-trip.
3. session_reader.set_current_tool / get_current_tool round-trip, including
   clearing.
4. main._silence_seconds computes from last_output_at, not from message-send
   time — a session state assertion around a simulated turn (per the plan's
   Test line for A3/A5).
5. is_active() reports True for a live Cursor session (A3 fix — it used to
   always report False since Cursor never touches session_manager._sessions).
6. GET /sessions surfaces the liveness fields end-to-end.
"""

import time
from datetime import datetime, timedelta

import pytest
from httpx import AsyncClient, ASGITransport

import devscope_bridge.main as bridge_main
import devscope_bridge.session_manager as mgr
import devscope_bridge.session_manager_cursor as cursor_mgr
import devscope_bridge.session_reader as sr
import devscope_bridge.session_store as store
from devscope_bridge.main import app


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "SESSIONS_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(store, "BRIDGE_DIR", tmp_path)
    mgr._sessions.clear()
    sr._last_output_at.clear()
    sr._current_tool.clear()
    sr._pending_permissions.clear()
    cursor_mgr._cursor_out_queues.clear()
    cursor_mgr._cursor_running.clear()
    cursor_mgr._cursor_current_proc.clear()
    cursor_mgr._cursor_turn_queues.clear()
    yield
    mgr._sessions.clear()
    sr._last_output_at.clear()
    sr._current_tool.clear()
    sr._pending_permissions.clear()


class _FakeProc:
    """Doubles as both an asyncio.subprocess.Process (returncode attr, for
    Claude) and a subprocess.Popen (poll() method, for Cursor)."""
    def __init__(self, pid=1234, returncode=None):
        self.pid = pid
        self.returncode = returncode

    def poll(self):
        return self.returncode


def _fake_active(name: str, turn_running: bool = True) -> mgr._ActiveSession:
    turn_done = __import__("asyncio").Event()
    if not turn_running:
        turn_done.set()
    active = mgr._ActiveSession(
        name=name, session_id="sid", proc=_FakeProc(),
        out_queue=__import__("asyncio").Queue(),
        reader_task=None, idle_task=None,
        mode=None, model=None, turn_done=turn_done,
    )
    mgr._sessions[name] = active
    return active


# ─────────────────────────────────────────────
# 1–3. session_reader liveness helpers
# ─────────────────────────────────────────────

def test_touch_output_and_get_round_trip():
    assert sr.get_last_output_at("fresh-sess") is None
    before = time.time()
    sr.touch_output("fresh-sess")
    after = time.time()
    ts = sr.get_last_output_at("fresh-sess")
    assert ts is not None
    assert before <= ts <= after


def test_current_tool_set_and_clear():
    assert sr.get_current_tool("t-sess") is None
    sr.set_current_tool("t-sess", "Bash")
    assert sr.get_current_tool("t-sess") == "Bash"
    sr.set_current_tool("t-sess", None)
    assert sr.get_current_tool("t-sess") is None


# ─────────────────────────────────────────────
# 4–5. Two independent clocks + turn_elapsed_s + cursor active fix
# ─────────────────────────────────────────────

def test_get_session_state_exposes_both_clocks_independently():
    store.create_session_metadata("clock-sess", "claude", store.DEFAULT_CWD)
    active = _fake_active("clock-sess", turn_running=True)
    # User message dispatched 5 minutes ago...
    active.last_msg_at = datetime.now() - timedelta(minutes=5)
    active.turn_started_at = datetime.now() - timedelta(seconds=30)
    # ...but the process just produced real stdout 1 second ago.
    sr.touch_output("clock-sess")

    state = mgr.get_session_state("clock-sess")
    assert state is not None
    assert state["last_user_msg_at"] == active.last_msg_at.isoformat()
    assert state["last_output_at"] is not None
    # The two clocks disagree by roughly 5 minutes — proving they are NOT the
    # same value (the old "last_msg_at" bug conflated them).
    age_from_output = time.time() - state["last_output_at"]
    assert age_from_output < 5.0
    assert state["turn_elapsed_s"] is not None
    assert 25 < state["turn_elapsed_s"] < 35


def test_silence_seconds_uses_last_output_at_not_message_time(monkeypatch):
    store.create_session_metadata("silence-sess", "claude", store.DEFAULT_CWD)
    active = _fake_active("silence-sess", turn_running=True)
    active.last_msg_at = datetime.now() - timedelta(minutes=10)  # long ago
    sr.touch_output("silence-sess")  # but output just happened

    silence = bridge_main._silence_seconds("silence-sess")
    assert silence < 2.0, (
        "Silence must be measured from last_output_at (fresh), not from the "
        "10-minute-old message dispatch time"
    )


def test_is_active_true_for_live_cursor_session():
    """A3 fix: Cursor liveness used to be hardcoded False (never touches
    session_manager._sessions)."""
    store.create_session_metadata("cursor-live", "cursor", store.DEFAULT_CWD)
    assert mgr.is_active("cursor-live") is False  # nothing running yet

    cursor_mgr._cursor_running["cursor-live"] = True
    cursor_mgr._cursor_current_proc["cursor-live"] = _FakeProc(pid=99, returncode=None)
    assert mgr.is_active("cursor-live") is True

    cursor_mgr._cursor_running.pop("cursor-live", None)
    cursor_mgr._cursor_current_proc.pop("cursor-live", None)


# ─────────────────────────────────────────────
# 6. GET /sessions end-to-end
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_sessions_surfaces_liveness_fields():
    store.create_session_metadata("live-ep", "claude", store.DEFAULT_CWD)
    active = _fake_active("live-ep", turn_running=True)
    active.turn_started_at = datetime.now() - timedelta(seconds=5)
    sr.touch_output("live-ep")
    sr.set_current_tool("live-ep", "Reading")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        resp = await client.get(
            "/sessions", headers={"Authorization": "Bearer test-token-abc123"},
        )
    assert resp.status_code == 200
    entry = resp.json()["sessions"]["live-ep"]
    assert entry["current_tool"] == "Reading"
    assert entry["last_output_at"] is not None
    assert entry["turn_elapsed_s"] is not None
    assert entry["queued_turns"] == 0
    assert entry["awaiting"] is None
