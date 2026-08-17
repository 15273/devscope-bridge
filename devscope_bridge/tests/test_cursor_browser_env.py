"""Cursor subprocess gets DEVSCOPE_SESSION for browser MCP routing."""

import os

from devscope_bridge import session_manager_cursor as cursor_mod


def test_cursor_subprocess_sets_devscope_session(monkeypatch):
    captured: dict = {}

    # _iter_stdout_lines (B1) reads the raw fd via select()/os.read(), so the
    # fake stdout needs a real fileno() — a closed-write-end pipe gives an
    # immediate EOF, i.e. empty stdout.
    read_fd, write_fd = os.pipe()
    os.close(write_fd)

    class FakeStdout:
        def fileno(self):
            return read_fd

    class FakeProc:
        returncode = 0
        stdout = FakeStdout()
        stderr = iter([])  # _spawn_stderr_drain just iterates it

        def poll(self):
            return 0

        def wait(self, timeout=None):
            return 0

    def fake_popen(cmd, **kwargs):
        captured.update(kwargs)
        return FakeProc()

    monkeypatch.setattr(cursor_mod.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(cursor_mod, "_resolve_cursor_bin", lambda: "/bin/cursor-agent")
    monkeypatch.setattr(cursor_mod, "find_devscope_workspace", lambda _cwd: "/repo")
    monkeypatch.setattr(cursor_mod.session_store, "upsert_session", lambda *_a, **_k: None)

    loop = __import__("asyncio").new_event_loop()
    q = __import__("asyncio").Queue()
    try:
        cursor_mod._run_cursor_streaming_blocking(
            "hi", None, "/tmp", "act", None, loop, q, "my-session",
        )
    finally:
        os.close(read_fd)

    assert captured["env"]["DEVSCOPE_SESSION"] == "my-session"
