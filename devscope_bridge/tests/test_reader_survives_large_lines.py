"""A single stream-json line can exceed 64 KiB (screenshot dataUrls, image
tool_results reach 100KB-1MB).  asyncio's default StreamReader limit is 64 KiB,
so `async for raw in proc.stdout` raises ValueError mid-turn and the reader
dies silently: no more frames reach the panel, the turn never completes, and
the watchdog/idle-eviction kill the session.  _spawn_claude_proc must create
the subprocess with a stream limit large enough for real tool results.
"""
import asyncio
import json
import sys

import pytest

from devscope_bridge import session_lifecycle

BIG = 300_000  # bytes — matches real image tool_result lines (149KB-843KB seen)


@pytest.mark.asyncio
async def test_spawned_proc_stdout_survives_lines_over_64kib(monkeypatch):
    emit = (
        "import json,sys;"
        f"sys.stdout.write(json.dumps({{'type':'user','pad':'x'*{BIG}}})+'\\n');"
        "sys.stdout.write(json.dumps({'type':'result'})+'\\n')"
    )
    monkeypatch.setattr(
        session_lifecycle, "_build_claude_args",
        lambda *a, **k: [sys.executable, "-c", emit],
    )

    proc = await session_lifecycle._spawn_claude_proc(None, cwd="/tmp")
    events = []
    async for raw in proc.stdout:  # same consumption pattern as session_reader
        events.append(json.loads(raw))
    await proc.wait()

    assert [e["type"] for e in events] == ["user", "result"]
    assert len(events[0]["pad"]) == BIG
