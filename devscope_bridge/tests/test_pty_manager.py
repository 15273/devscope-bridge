"""
test_pty_manager.py — Real-PTY terminal subsystem (additive; separate from
the stream-json session model).

1. build_argv: resume (with/without stored session_id), claude, shell.
2. A real PTY round-trip: spawn /bin/echo under a PTY, read its output, hit EOF.
3. write_input / resize on an unknown terminal id are safe no-ops.
"""

import asyncio
import pytest

import devscope_bridge.pty_manager as pm


@pytest.fixture(autouse=True)
def clean_terminals():
    for tid in list(pm._terminals):
        pm.close_terminal(tid)
    yield
    for tid in list(pm._terminals):
        pm.close_terminal(tid)


# ─────────────────────────────────────────────
# 1. build_argv
# ─────────────────────────────────────────────

def test_build_argv_resume_with_session_id(monkeypatch):
    monkeypatch.setattr(pm.session_store, "get_metadata", lambda n: {"cwd": "/proj"})
    monkeypatch.setattr(pm.session_store, "get_session", lambda n: {"session_id": "sid-7"})
    argv, cwd = pm.build_argv("resume", "ns")
    assert argv == ["claude", "--resume", "sid-7"]
    assert cwd == "/proj"


def test_build_argv_resume_without_session_id_falls_back(monkeypatch):
    monkeypatch.setattr(pm.session_store, "get_metadata", lambda n: {"cwd": "/proj"})
    monkeypatch.setattr(pm.session_store, "get_session", lambda n: {"session_id": ""})
    argv, _ = pm.build_argv("resume", "ns")
    assert argv == ["claude"]


def test_build_argv_shell(monkeypatch):
    monkeypatch.setenv("SHELL", "/bin/zsh")
    argv, _ = pm.build_argv("shell", None)
    assert argv == ["/bin/zsh"]


# ─────────────────────────────────────────────
# 2. Real PTY round-trip
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_resume_terminal_evicts_chat_process(monkeypatch):
    """Opening a resume terminal first kills the chat's --print process (no dual resume)."""
    killed = []

    async def fake_kill(name):
        killed.append(name)

    monkeypatch.setattr(pm.session_manager, "kill_session", fake_kill)
    monkeypatch.setattr(pm.session_manager, "is_turn_running", lambda n: False)  # idle
    monkeypatch.setattr(pm, "build_argv", lambda cmd, s: (["/bin/echo", "x"], "/tmp"))

    await pm.open_terminal("t-resume", "resume", "ns")
    assert killed == ["ns"]
    pm.close_terminal("t-resume")


@pytest.mark.asyncio
async def test_resume_terminal_rejected_when_chat_turn_running(monkeypatch):
    """A6/RC-2: opening --resume during a running chat turn is refused, not
    spawned alongside it — two `claude --resume <same id>` processes racing
    the same conversation is the exact cause of a prior wedge incident."""
    killed = []
    spawned = []

    async def fake_kill(name):
        killed.append(name)

    async def fake_spawn(*args, **kwargs):
        spawned.append(args)
        raise AssertionError("must not spawn a subprocess when rejecting")

    monkeypatch.setattr(pm.session_manager, "kill_session", fake_kill)
    monkeypatch.setattr(pm.session_manager, "is_turn_running", lambda n: True)  # mid-task
    monkeypatch.setattr(pm, "build_argv", lambda cmd, s: (["/bin/echo", "x"], "/tmp"))
    monkeypatch.setattr(pm.asyncio, "create_subprocess_exec", fake_spawn)

    with pytest.raises(pm.PtyConflictError):
        await pm.open_terminal("t-coexist", "resume", "ns")

    assert killed == []       # running task left alone
    assert spawned == []      # no PTY process spawned
    assert "t-coexist" not in pm._terminals


@pytest.mark.asyncio
async def test_shell_terminal_does_not_evict(monkeypatch):
    """A plain shell/claude terminal does NOT touch any chat session."""
    killed = []

    async def fake_kill(name):
        killed.append(name)

    monkeypatch.setattr(pm.session_manager, "kill_session", fake_kill)
    monkeypatch.setattr(pm, "build_argv", lambda cmd, s: (["/bin/echo", "x"], "/tmp"))

    await pm.open_terminal("t-shell", "shell", None)
    assert killed == []
    pm.close_terminal("t-shell")


@pytest.mark.asyncio
async def test_pty_echo_roundtrip(monkeypatch):
    monkeypatch.setattr(pm, "build_argv", lambda cmd, s: (["/bin/echo", "pty-hello"], "/tmp"))

    term = await pm.open_terminal("t-echo", "shell", None)
    collected = []
    while True:
        item = await asyncio.wait_for(term.out_queue.get(), timeout=3.0)
        if item is None:  # EOF
            break
        collected.append(item)

    assert "pty-hello" in "".join(collected)
    pm.close_terminal("t-echo")
    assert "t-echo" not in pm._terminals


# ─────────────────────────────────────────────
# 3. Safe no-ops on unknown terminals
# ─────────────────────────────────────────────

def test_write_and_resize_unknown_terminal_are_noops():
    pm.write_input("does-not-exist", "hello")   # must not raise
    pm.resize("does-not-exist", 120, 40)         # must not raise


# ─────────────────────────────────────────────
# 4. Single-owner: terminal_for_session + incomplete-turn cleanup
# ─────────────────────────────────────────────

import asyncio as _asyncio  # noqa: E402
from unittest.mock import AsyncMock, MagicMock  # noqa: E402


def test_terminal_for_session_finds_live_owner():
    term = pm._Terminal("t-ns", 0, 1234, _asyncio.Queue(), MagicMock(), session_name="ns")
    pm._terminals["t-ns"] = term
    assert pm.terminal_for_session("ns") == "t-ns"
    assert pm.terminal_for_session("other") is None
    term.closed = True
    assert pm.terminal_for_session("ns") is None  # closed → not a live owner


def test_close_terminal_never_clears_session_id(monkeypatch):
    """close_terminal preserves session_id — conversation survives the next --resume."""
    cleared = []
    monkeypatch.setattr(pm.session_store, "transcript_ends_incomplete", lambda n: True)
    monkeypatch.setattr(pm.session_store, "clear_session_id", lambda n: cleared.append(n))
    term = pm._Terminal("t-x", 0, 999999, _asyncio.Queue(), MagicMock(), session_name="ns")
    pm._terminals["t-x"] = term

    pm.close_terminal("t-x")
    assert cleared == []


def test_open_terminal_replaces_existing(monkeypatch):
    """Reopening the same terminal_id must not leak the old master fd / process."""
    closed = []
    old = pm._Terminal("chat-ns", 11, 1111, _asyncio.Queue(), MagicMock(), session_name="ns")
    pm._terminals["chat-ns"] = old
    monkeypatch.setattr(pm, "close_terminal", lambda tid: closed.append(tid))
    monkeypatch.setattr(pm.session_manager, "is_turn_running", lambda n: False)
    monkeypatch.setattr(pm.session_manager, "kill_session", AsyncMock())
    monkeypatch.setattr(pm, "build_argv", lambda cmd, sn: (["echo", "hi"], "/tmp"))
    monkeypatch.setattr(
        pm.asyncio, "create_subprocess_exec",
        AsyncMock(return_value=MagicMock(pid=2222)),
    )
    monkeypatch.setattr(pm.pty, "openpty", lambda: (12, 13))
    monkeypatch.setattr(pm.os, "close", lambda fd: None)
    monkeypatch.setattr(pm, "_set_winsize", lambda *a, **k: None)

    def _fake_create_task(coro):
        coro.close()
        return MagicMock()

    monkeypatch.setattr(pm.asyncio, "create_task", _fake_create_task)

    async def _run():
        await pm.open_terminal("chat-ns", "resume", "ns")

    _asyncio.run(_run())
    assert closed == ["chat-ns"]
    pm._terminals.clear()


def test_resolve_terminal_params_chat_prefix():
    cmd, session = pm.resolve_terminal_params("chat-my-session", "shell", None)
    assert cmd == "resume"
    assert session == "my-session"


def test_resolve_terminal_params_passthrough():
    cmd, session = pm.resolve_terminal_params("term-1", "claude", "other")
    assert cmd == "claude"
    assert session == "other"


def test_ingest_pty_output_binds_session_id(monkeypatch):
    upserted = []
    monkeypatch.setattr(pm.session_store, "session_id_owner", lambda sid: None)
    monkeypatch.setattr(pm.session_store, "get_session", lambda n: {"session_id": ""})
    monkeypatch.setattr(
        pm.session_store, "upsert_session",
        lambda name, sid: upserted.append((name, sid)),
    )
    term = pm._Terminal(
        "chat-sepfxc", 0, 1234, _asyncio.Queue(), MagicMock(),
        session_name="sepfxc",
    )
    pm._terminals["chat-sepfxc"] = term
    chunk = '{"type":"system","sessionId":"dddddddd-dddd-dddd-dddd-dddddddddddd"}\n'
    pm.ingest_pty_output("chat-sepfxc", chunk)
    assert upserted == [("sepfxc", "dddddddd-dddd-dddd-dddd-dddddddddddd")]
    assert term.claude_session_id == "dddddddd-dddd-dddd-dddd-dddddddddddd"


def test_ingest_pty_output_does_not_steal_owned_uuid(monkeypatch):
    upserted = []
    monkeypatch.setattr(
        pm.session_store, "session_id_owner",
        lambda sid: "other-chat" if sid == "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee" else None,
    )
    monkeypatch.setattr(pm.session_store, "get_session", lambda n: {"session_id": ""})
    monkeypatch.setattr(
        pm.session_store, "upsert_session",
        lambda name, sid: upserted.append((name, sid)),
    )
    term = pm._Terminal(
        "chat-sepfxc", 0, 1234, _asyncio.Queue(), MagicMock(),
        session_name="sepfxc",
    )
    pm._terminals["chat-sepfxc"] = term
    chunk = '{"sessionId":"eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"}\n'
    pm.ingest_pty_output("chat-sepfxc", chunk)
    assert upserted == []
    assert term.claude_session_id is None


def test_two_terminals_isolated_session_ids(monkeypatch):
    """PTY output on chat-A must not assign UUID to chat-B."""
    upserted = []
    monkeypatch.setattr(pm.session_store, "session_id_owner", lambda sid: None)
    monkeypatch.setattr(pm.session_store, "get_session", lambda n: {"session_id": ""})
    monkeypatch.setattr(
        pm.session_store, "upsert_session",
        lambda name, sid: upserted.append((name, sid)),
    )
    term_a = pm._Terminal(
        "chat-a", 0, 1, _asyncio.Queue(), MagicMock(), session_name="session_a",
    )
    term_b = pm._Terminal(
        "chat-b", 0, 2, _asyncio.Queue(), MagicMock(), session_name="session_b",
    )
    pm._terminals["chat-a"] = term_a
    pm._terminals["chat-b"] = term_b
    pm.ingest_pty_output("chat-a", '{"sessionId":"ffffffff-ffff-ffff-ffff-ffffffffffff"}')
    pm.ingest_pty_output("chat-b", '{"sessionId":"11111111-1111-1111-1111-111111111111"}')
    assert upserted == [
        ("session_a", "ffffffff-ffff-ffff-ffff-ffffffffffff"),
        ("session_b", "11111111-1111-1111-1111-111111111111"),
    ]
    pm._terminals.clear()


@pytest.mark.asyncio
async def test_open_terminal_uses_client_winsize(monkeypatch):
    winsizes = []
    monkeypatch.setattr(pm.session_manager, "kill_session", AsyncMock())
    monkeypatch.setattr(pm.session_manager, "is_turn_running", lambda n: False)
    monkeypatch.setattr(pm, "build_argv", lambda cmd, s: (["/bin/echo", "x"], "/tmp"))
    monkeypatch.setattr(pm, "_set_winsize", lambda fd, c, r: winsizes.append((c, r)))

    await pm.open_terminal("t-size", "shell", None, cols=52, rows=18)
    assert (52, 18) in winsizes
    pm.close_terminal("t-size")
