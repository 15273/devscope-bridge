"""
session_manager_cursor.py — Cursor CLI dispatch for dev_bridge.

Runs cursor-agent as a streaming subprocess in asyncio.to_thread so the event
loop is never blocked. Emits SessionReady + AiChunk (one per delta) + AiDone /
AiError onto a queue — same contract as the Claude streaming path.

Architecture note — one-shot (not persistent)
----------------------------------------------
cursor-agent does NOT support a persistent stdin-based multi-turn protocol the
way `claude --input-format stream-json` does.  Each turn is a fresh subprocess
invocation.  Session continuity is preserved via `--resume <chatId>` which
cursor-agent accepts and uses to re-hydrate the conversation from its backend.

Streaming output
----------------
`--output-format stream-json --stream-partial-output` causes cursor-agent to
emit newline-delimited JSON to stdout.  We parse assistant deltas and push
AiChunk frames as lines arrive (not only after the process exits).

If cursor-agent is absent, an AiError is emitted immediately — no crash.

Binary resolution order
-----------------------
1. CURSOR_BIN env var (explicit override)
2. shutil.which("cursor-agent")          — installed via curl https://cursor.com/install
3. ~/.local/bin/cursor-agent             — default install location
4. /Applications/Cursor.app/Contents/Resources/app/bin/cursor  — legacy fallback
"""

import asyncio
import json
import logging
import os
import select
import shutil
import signal
import subprocess
import threading
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from devscope_bridge import cursor_watchdog
from devscope_bridge import session_store
from devscope_bridge.cursor_workspace import find_devscope_workspace
from devscope_bridge.cursor_stream_parser import (
    assistant_tool_activities,
    cursor_tool_activity_from_event,
)
from devscope_bridge.models import AiChunk, AiDone, AiError, AgentActivity, SessionReady, TurnState
from devscope_bridge.mode_presets import MODE_PRESETS

logger = logging.getLogger(__name__)

# One stable out_queue per Cursor session (mirrors Claude persistent queues).
_cursor_out_queues: dict[str, asyncio.Queue] = {}
_cursor_turn_queues: dict[str, asyncio.Queue] = {}
_cursor_workers: dict[str, asyncio.Task] = {}
_cursor_current_proc: dict[str, subprocess.Popen] = {}
_cursor_running: dict[str, bool] = {}
# Wall-clock time of the last user message dispatched to this session —
# mirrors Claude's active.last_msg_at, read by main.py's silence calculation
# and watchdog_medic (contract 2 — B5).
_cursor_last_msg_at: dict[str, datetime] = {}

_STDERR_TAIL_LINES = 200


@dataclass(frozen=True)
class _CursorTurn:
    prompt: str
    prior_session_id: str | None
    cwd: str
    mode: str | None
    model: str | None


def get_out_queue(name: str) -> asyncio.Queue | None:
    return _cursor_out_queues.get(name)


def is_busy(name: str) -> bool:
    if _cursor_running.get(name):
        return True
    q = _cursor_turn_queues.get(name)
    return q is not None and not q.empty()


def get_session_state(name: str) -> dict | None:
    """Runtime snapshot for watchdog medic + `/sessions` (Cursor one-shot worker).

    Exposes cross-workstream contract 2's liveness keys so WS-A's `/sessions`
    builder and the medic can read Cursor state the same way as Claude
    sessions: last_msg_at, last_output_at, current_tool, turn_elapsed_s,
    queued_turns, awaiting (always None — cursor's one-shot path has no
    interactive pending-request concept).
    """
    running = _cursor_running.get(name, False)
    proc = _cursor_current_proc.get(name)
    turn_q = _cursor_turn_queues.get(name)
    queued_turns = turn_q.qsize() if turn_q is not None else 0
    if not running and queued_turns == 0 and (proc is None or proc.poll() is not None):
        return None
    entry = session_store.get_session(name)
    last_msg_at = _cursor_last_msg_at.get(name)
    return {
        "name": name,
        "agent": "cursor",
        "pid": proc.pid if proc is not None else None,
        "returncode": proc.poll() if proc is not None else None,
        "turn_done": not running and queued_turns == 0,
        "pending_turns": queued_turns,  # legacy alias, kept for compatibility
        "session_id": entry.get("session_id") if entry else None,
        "mode": entry.get("mode") if entry else None,
        "model": entry.get("model") if entry else None,
        "last_msg_at": last_msg_at.isoformat() if last_msg_at else None,
        "last_output_at": cursor_watchdog.get_last_output_epoch(name),
        "current_tool": cursor_watchdog.get_current_tool(name),
        "turn_elapsed_s": cursor_watchdog.get_turn_elapsed_s(name),
        "queued_turns": queued_turns,
        "awaiting": None,
    }


def _drain_queued_turns(name: str) -> int:
    """Remove all not-yet-started turns from the queue; return how many."""
    turn_q = _cursor_turn_queues.get(name)
    if turn_q is None:
        return 0
    cancelled = 0
    while not turn_q.empty():
        try:
            turn_q.get_nowait()
            cancelled += 1
        except asyncio.QueueEmpty:
            break
    return cancelled


def interrupt_cursor(name: str) -> bool:
    """Kill the in-flight cursor-agent subprocess AND drain queued turns.

    Killing the subprocess alone (the old behavior) let queued turns start
    right after — Stop didn't actually stop anything beyond the current turn
    (cursor RC-6 / B4). Draining the queue here means Stop cancels everything
    the user hasn't seen run yet.
    """
    proc = _cursor_current_proc.get(name)
    running = _cursor_running.get(name, False)
    pending = bool(_cursor_turn_queues.get(name) and not _cursor_turn_queues[name].empty())
    if not running and not pending and (proc is None or proc.poll() is not None):
        return False

    cancelled = _drain_queued_turns(name)
    if cancelled:
        logger.info("Cancelled %d queued cursor turn(s) for session '%s'", cancelled, name)
        out_q = _cursor_out_queues.get(name)
        if out_q is not None:
            label = f"Stopped — {cancelled} queued turn(s) cancelled"
            out_q.put_nowait(AgentActivity(session=name, label=label))

    if proc is not None and proc.poll() is None:
        try:
            proc.kill()
            logger.info("Killed cursor-agent pid=%d for session '%s'", proc.pid, name)
        except ProcessLookupError:
            pass
        return True
    return running or pending


def shutdown_cursor_session(name: str) -> None:
    """Stop worker, drain pending turns, and drop per-session cursor state."""
    proc = _cursor_current_proc.pop(name, None)
    if proc is not None and proc.poll() is None:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
    _cursor_running.pop(name, None)
    _cursor_turn_queues.pop(name, None)
    _cursor_out_queues.pop(name, None)
    _cursor_last_msg_at.pop(name, None)
    task = _cursor_workers.pop(name, None)
    if task is not None and not task.done():
        task.cancel()

# ─────────────────────────────────────────────
# Binary resolution
# ─────────────────────────────────────────────

_CURSOR_APP_BIN = "/Applications/Cursor.app/Contents/Resources/app/bin/cursor"
_LOCAL_BIN = str(Path.home() / ".local" / "bin" / "cursor-agent")


def _resolve_cursor_bin() -> str | None:
    """Return the best available cursor-agent binary path, or None if absent."""
    env_override = os.environ.get("CURSOR_BIN")
    if env_override:
        return env_override if os.path.exists(env_override) else None

    which = shutil.which("cursor-agent")
    if which:
        return which
    if os.path.exists(_LOCAL_BIN):
        return _LOCAL_BIN

    if os.path.exists(_CURSOR_APP_BIN):
        return _CURSOR_APP_BIN

    return None


# ─────────────────────────────────────────────
# Session-id extraction
# ─────────────────────────────────────────────

def _looks_like_uuid(s: str) -> bool:
    parts = s.split("-")
    return (
        len(parts) == 5
        and all(p.isalnum() for p in parts)
        and [len(p) for p in parts] == [8, 4, 4, 4, 12]
    )


def _session_id_from_obj(obj: dict) -> str | None:
    sid = obj.get("session_id") or obj.get("id")
    if sid and _looks_like_uuid(str(sid)):
        return str(sid)
    return None


def _extract_session_id_from_lines(lines: list[str]) -> str | None:
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            obj = json.loads(stripped)
            sid = _session_id_from_obj(obj)
            if sid:
                return sid
        except (json.JSONDecodeError, AttributeError):
            pass
        if _looks_like_uuid(stripped):
            return stripped
        break
    return None


# ─────────────────────────────────────────────
# Argument builder
# ─────────────────────────────────────────────

def _cursor_agent_env(session_name: str | None, cwd: str | None = None) -> dict[str, str]:
    """Mirror session_manager.subscription_env — tags MCP children with DEVSCOPE_SESSION."""
    env = dict(os.environ)
    if os.environ.get("DEVSCOPE_USE_API_KEY") != "1":
        env.pop("ANTHROPIC_API_KEY", None)
        env.pop("ANTHROPIC_AUTH_TOKEN", None)
    if session_name:
        env["DEVSCOPE_SESSION"] = session_name
    workspace = find_devscope_workspace(cwd or os.getcwd())
    if workspace:
        env["DEVSCOPE_REPO_ROOT"] = workspace
    return env


def _build_cursor_args(
    binary: str,
    prompt: str,
    prior_session_id: str | None,
    mode: str | None,
    model: str | None,
    *,
    workspace: str | None = None,
) -> list[str]:
    """Build the cursor-agent argv for a single-turn invocation."""
    is_standalone = "cursor-agent" in os.path.basename(binary)

    if is_standalone:
        cmd = [
            binary, "--print",
            "--output-format", "stream-json",
            "--stream-partial-output",
            "--trust",
            "--approve-mcps",
            "--force",
        ]
        if workspace:
            cmd += ["--workspace", workspace]
    else:
        cmd = [
            binary, "agent", "--print",
            "--output-format", "stream-json",
            "--stream-partial-output",
            "--trust",
            "--approve-mcps",
            "--force",
        ]
        if workspace:
            cmd += ["--workspace", workspace]

    if prior_session_id:
        cmd += ["--resume", prior_session_id]

    if model:
        cmd += ["--model", model]

    preset = MODE_PRESETS.get(mode or "act")
    if preset:
        cursor_args = preset["cursor_args"]
        suffix = preset["system_prompt_suffix"]
        if cursor_args:
            cmd += cursor_args
        elif suffix:
            prompt = suffix + "\n\n" + prompt

    cmd.append(prompt)
    return cmd


# ─────────────────────────────────────────────
# Streaming parser (cursor-agent stream-json)
# ─────────────────────────────────────────────

def _assistant_text_from_obj(obj: dict) -> str | None:
    if obj.get("type") != "assistant":
        return None
    msg = obj.get("message")
    if not isinstance(msg, dict):
        return None
    content = msg.get("content")
    if not isinstance(content, list):
        return None
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
            parts.append(str(block["text"]))
    return "".join(parts) if parts else None


def _delta_from_cumulative(cumulative: str, accum: str) -> tuple[str, str]:
    """Map cursor-agent cumulative assistant text to an append-only delta.

    Only suppresses a delta when `cumulative` is genuinely an earlier state of
    what we've already shown (accum.startswith(cumulative) — a shrink-back).
    The old `cumulative in accum` check matched ANY substring occurrence
    anywhere in accum, which silently dropped legitimate new/repeated text
    that merely happened to reappear earlier in the transcript (cursor RC-9).
    """
    if not cumulative:
        return "", accum
    if cumulative == accum:
        return "", accum
    if accum and cumulative.startswith(accum):
        return cumulative[len(accum):], cumulative
    if accum and accum.startswith(cumulative):
        return "", accum
    return cumulative, cumulative


def _cursor_activities_from_obj(obj: dict) -> list[tuple[str, str, str | None, str | None]]:
    """Extract UI activity tuples — (label, tool, detail, status) — from one
    stream-json object. status is "running" | "done" | "error"."""
    ev_type = obj.get("type", "")
    if ev_type == "tool_call":
        one = cursor_tool_activity_from_event(obj)
        return [one] if one else []
    if ev_type == "assistant":
        msg = obj.get("message")
        if isinstance(msg, dict) and isinstance(msg.get("content"), list):
            return assistant_tool_activities(msg["content"])
    return []


def _delta_from_result(out: object, accum: str, session_id: str | None) -> tuple[str | None, str, str | None]:
    """Map a `result` event's final text to a delta against the streamed accum.

    Previously any `result` text was discarded whenever accum was non-empty —
    even when the result contained genuinely different/additional content
    (cursor RC-9). Now the result is only suppressed when it's a prefix of
    (or identical to) what streaming deltas already produced; anything beyond
    that is emitted as new content.
    """
    if not out:
        return None, accum, session_id
    out_str = str(out)
    if not accum:
        return out_str, out_str, session_id
    if out_str == accum or accum.startswith(out_str):
        return None, accum, session_id
    if out_str.startswith(accum):
        delta = out_str[len(accum):]
        return (delta or None), out_str, session_id
    return out_str, accum + out_str, session_id


def _parse_line_to_delta(line: str, accum: str) -> tuple[str | None, str, str | None]:
    """
    Parse one stdout line → (text_delta, new_accum, session_id_on_line).
    Returns None delta when there is nothing new to append.
    """
    stripped = line.strip()
    if not stripped:
        return None, accum, None

    session_id: str | None = None
    try:
        obj = json.loads(stripped)
        session_id = _session_id_from_obj(obj)
        ev_type = obj.get("type", "")

        if ev_type == "assistant":
            text = _assistant_text_from_obj(obj)
            if not text:
                return None, accum, session_id
            delta, new_accum = _delta_from_cumulative(text, accum)
            return (delta if delta else None), new_accum, session_id

        if ev_type == "text_delta":
            t = obj.get("text")
            return (str(t) if t else None), accum, session_id

        if ev_type in ("content", "partial"):
            t = obj.get("text") or obj.get("content")
            return (str(t) if t else None), accum, session_id

        if ev_type == "result":
            return _delta_from_result(obj.get("result") or obj.get("output") or obj.get("text"), accum, session_id)

        return None, accum, session_id
    except json.JSONDecodeError:
        # A line that looks like it was meant to be JSON (starts with `{`/`[`)
        # but fails to parse is a malformed/truncated fragment — never leak it
        # into the chat as raw text (cursor RC-9). Genuine plain-text output
        # from the legacy (non-stream-json) binary doesn't look like JSON, so
        # it still falls through to the chat-text fallback below.
        if stripped.startswith(("{", "[")):
            return None, accum, None
        return stripped, accum, session_id


def _parse_chunk_from_event(line: str) -> str | None:
    """Legacy helper — parse a single line to a chunk (used in tests)."""
    delta, _, _ = _parse_line_to_delta(line, "")
    return delta


# ─────────────────────────────────────────────
# Blocking runner (streams lines to asyncio queue)
# ─────────────────────────────────────────────

def _iter_stdout_lines(proc: subprocess.Popen):
    """Yield each stdout line as it arrives — a true streaming generator.

    THE cursor bug (B1): the old version collected every line into a list and
    only `return`ed it after the process exited, so the `for line in
    _iter_stdout_lines(proc)` caller consumed everything post-mortem — no
    live AiChunk/AgentActivity, no live touch_stdout for the watchdog.

    Reads the raw fd via os.read() instead of the buffered
    TextIOWrapper.readline(), so a long line arriving in several chunks never
    blocks waiting to see a trailing newline before yielding anything — we
    only ever read bytes select() has already told us are available, and
    buffer the (possibly partial) remainder ourselves.
    """
    assert proc.stdout is not None
    fd = proc.stdout.fileno()
    buf = b""
    while True:
        if proc.poll() is not None:
            ready, _, _ = select.select([fd], [], [], 0)
            if not ready:
                break
        else:
            ready, _, _ = select.select([fd], [], [], 1.0)
            if not ready:
                continue
        chunk = os.read(fd, 65536)
        if not chunk:
            break
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            yield line.decode("utf-8", errors="replace")
    if buf:
        yield buf.decode("utf-8", errors="replace")


def _spawn_stderr_drain(proc: subprocess.Popen) -> deque:
    """Drain stderr on a daemon thread from spawn time (B2).

    `stderr=PIPE` fills a fixed OS pipe buffer (~64KB); if nobody reads it
    while stdout is being consumed, a verbose child (MCP logging, etc.) can
    block on its own stderr write — wedging the whole turn until the 60s
    `proc.wait(timeout=...)` fires. Draining concurrently into a bounded
    deque removes that deadlock risk while still keeping a tail for errors.
    """
    buf: deque = deque(maxlen=_STDERR_TAIL_LINES)

    def _drain() -> None:
        assert proc.stderr is not None
        try:
            for line in proc.stderr:
                buf.append(line)
        except (ValueError, OSError):
            pass

    threading.Thread(target=_drain, daemon=True, name="cursor-stderr-drain").start()
    return buf


def _emit_activity_events(obj: dict, session_name: str, put) -> None:
    """Emit AgentActivity for tool events in `obj`; track current_tool (B6)."""
    for label, tool, detail, status in _cursor_activities_from_obj(obj):
        cursor_watchdog.touch_stdout(session_name)
        if status == "running":
            cursor_watchdog.set_current_tool(session_name, tool)
        elif status in ("done", "error"):
            cursor_watchdog.set_current_tool(session_name, None)
        put(AgentActivity(session=session_name, label=label, tool=tool, detail=detail, status=status))


def _nonzero_exit_tail(proc: subprocess.Popen, stderr_tail: str, stdout_lines: list[str]) -> str:
    """Build the AiError tail text for a non-zero-exit or signal-killed turn."""
    if proc.returncode < 0:
        sig = -proc.returncode
        try:
            sig_name = signal.Signals(sig).name
        except (ValueError, AttributeError):
            sig_name = str(sig)
        return f"[bridge] Turn stopped ({sig_name})"
    return stderr_tail[-500:] or (stdout_lines[-1] if stdout_lines else "")


def _emit_empty_output_result(
    session_name: str, stdout_lines: list[str], stderr_tail: str, put,
) -> tuple[bool, str]:
    """B3: a zero-exit turn with truly empty stdout must not look clean.

    If raw non-JSON stdout exists (legacy binary with no stream-json
    support), surface it as the chunk like before. If there is genuinely
    nothing, emit AiError with the stderr tail instead of a silent AiDone —
    returns (False, "") so the caller stops the turn as an error.
    """
    raw = "\n".join(stdout_lines).strip()
    if raw:
        put(AiChunk(session=session_name, text=raw))
        return True, raw
    tail = stderr_tail[-500:].strip() or "cursor-agent returned no output"
    put(AiError(session=session_name, exit_code=0, stderr_tail=tail))
    return False, ""


def _run_cursor_streaming_blocking(
    prompt: str,
    prior_session_id: str | None,
    cwd: str,
    mode: str | None,
    model: str | None,
    loop: asyncio.AbstractEventLoop,
    q: asyncio.Queue,
    session_name: str,
) -> None:
    """
    Blocking cursor-agent call; pushes frames onto `q` as stdout lines arrive.
  """
    binary = _resolve_cursor_bin()
    if not binary:
        raise FileNotFoundError(
            "cursor-agent not found. Install with: curl https://cursor.com/install -fsS | bash"
        )

    cmd = _build_cursor_args(
        binary, prompt, prior_session_id, mode, model,
        workspace=find_devscope_workspace(cwd),
    )
    logger.info(
        "cursor-agent session=%s DEVSCOPE_SESSION=%s workspace=%s",
        session_name,
        session_name,
        find_devscope_workspace(cwd),
    )

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=cwd,
        env=_cursor_agent_env(session_name, cwd),
    )
    _cursor_current_proc[session_name] = proc
    stderr_buf = _spawn_stderr_drain(proc)  # B2 — concurrent drain, no deadlock

    stdout_lines: list[str] = []
    accum = ""
    resolved_sid = prior_session_id
    session_ready_sent = False
    emitted_any = False

    def _put(frame) -> None:
        asyncio.run_coroutine_threadsafe(q.put(frame), loop)

    for line in _iter_stdout_lines(proc):
        cursor_watchdog.touch_stdout(session_name)
        stdout_lines.append(line)
        stripped = line.strip()
        if stripped:
            try:
                obj = json.loads(stripped)
                _emit_activity_events(obj, session_name, _put)
            except json.JSONDecodeError:
                pass
        delta, accum, sid_line = _parse_line_to_delta(line, accum)
        if sid_line:
            resolved_sid = sid_line
        if not session_ready_sent and resolved_sid:
            session_store.upsert_session(session_name, resolved_sid)
            _put(SessionReady(
                session=session_name,
                session_id=resolved_sid,
                resumed=bool(prior_session_id),
            ))
            session_ready_sent = True
        if delta:
            cursor_watchdog.touch_stdout(session_name)
            _put(AiChunk(session=session_name, text=delta))
            emitted_any = True

    try:
        proc.wait(timeout=60)
    finally:
        _cursor_current_proc.pop(session_name, None)

    stderr_out = "".join(stderr_buf)

    bridge_kill = cursor_watchdog.consume_kill_reason(session_name)
    if bridge_kill:
        _put(AiError(session=session_name, exit_code=-1, stderr_tail=bridge_kill))
        _put(TurnState(session=session_name, running=False))
        return

    if not session_ready_sent:
        new_sid = (
            _extract_session_id_from_lines(stdout_lines)
            or prior_session_id
            or str(uuid.uuid4())
        )
        session_store.upsert_session(session_name, new_sid)
        _put(SessionReady(
            session=session_name,
            session_id=new_sid,
            resumed=bool(prior_session_id),
        ))

    if proc.returncode != 0:
        tail = _nonzero_exit_tail(proc, stderr_out, stdout_lines)
        _put(AiError(session=session_name, exit_code=proc.returncode, stderr_tail=tail))
        _put(TurnState(session=session_name, running=False))
        return

    if not emitted_any:
        emitted_any, accum = _emit_empty_output_result(session_name, stdout_lines, stderr_out, _put)
        if not emitted_any:
            _put(TurnState(session=session_name, running=False))
            return

    if accum.strip():
        session_store.append_bridge_turn(session_name, "assistant", accum)

    _put(AiDone(session=session_name, exit_code=0))
    _put(TurnState(session=session_name, running=False))


def _run_cursor_streaming(
    prompt: str,
    prior_session_id: str | None,
    cwd: str,
    mode: str | None,
    model: str | None,
) -> tuple[int, list[str], str]:
    """
    Blocking cursor-agent call with streaming output (test shim).
    Returns (returncode, stdout_lines, stderr_tail) after the process exits.
    """
    binary = _resolve_cursor_bin()
    if not binary:
        raise FileNotFoundError(
            "cursor-agent not found. Install with: curl https://cursor.com/install -fsS | bash"
        )

    cmd = _build_cursor_args(
        binary, prompt, prior_session_id, mode, model,
        workspace=find_devscope_workspace(cwd),
    )
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=cwd,
        env=_cursor_agent_env(None),
    )
    stderr_buf = _spawn_stderr_drain(proc)  # B2 — avoid stderr-pipe deadlock
    stdout_lines: list[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        stdout_lines.append(line.rstrip("\n"))
    proc.wait(timeout=300)

    stderr_out = "".join(stderr_buf)
    return proc.returncode, stdout_lines, stderr_out[-500:]


# ─────────────────────────────────────────────
# Async dispatch
# ─────────────────────────────────────────────

def _ensure_cursor_worker(name: str) -> None:
    task = _cursor_workers.get(name)
    if task is not None and not task.done():
        return
    _cursor_workers[name] = asyncio.create_task(_cursor_worker(name))


async def _cursor_worker(name: str) -> None:
    """Drain the per-session turn queue — one cursor-agent subprocess at a time."""
    out_q = _cursor_out_queues[name]
    turn_q = _cursor_turn_queues[name]
    loop = asyncio.get_running_loop()

    while True:
        turn = await turn_q.get()
        _cursor_running[name] = True
        cursor_watchdog.begin_turn(name)
        medic_active = asyncio.Event()
        wd_task = asyncio.create_task(
            cursor_watchdog.run(
                name,
                out_q,
                is_running=lambda: _cursor_running.get(name, False),
                kill_proc=lambda: _kill_cursor_proc(name),
                medic_active=medic_active,
            ),
        )
        await out_q.put(TurnState(session=name, running=True))
        try:
            await asyncio.to_thread(
                _run_cursor_streaming_blocking,
                turn.prompt,
                turn.prior_session_id,
                turn.cwd,
                turn.mode,
                turn.model,
                loop,
                out_q,
                name,
            )
        except FileNotFoundError as exc:
            await out_q.put(AiError(session=name, exit_code=-1, stderr_tail=str(exc)))
            await out_q.put(TurnState(session=name, running=False))
        except Exception as exc:
            await out_q.put(AiError(session=name, exit_code=-1, stderr_tail=str(exc)))
            await out_q.put(TurnState(session=name, running=False))
        finally:
            _cursor_running[name] = False
            cursor_watchdog.end_turn(name)
            wd_task.cancel()
            try:
                await wd_task
            except asyncio.CancelledError:
                pass


def _kill_cursor_proc(name: str) -> None:
    proc = _cursor_current_proc.get(name)
    if proc is not None and proc.poll() is None:
        try:
            proc.kill()
            logger.info("Watchdog killed cursor-agent pid=%d for session '%s'", proc.pid, name)
        except ProcessLookupError:
            pass


async def dispatch_cursor(
    name: str,
    prompt: str,
    prior_session_id: str | None,
    cwd: str,
    mode: str | None = None,
    model: str | None = None,
) -> asyncio.Queue:
    """
    Enqueue a cursor-agent turn; a per-session worker runs subprocesses serially.

    Mid-turn messages from the extension are queued here (unlike Claude stdin
    steering). Stop/interrupt kills the active subprocess so the worker advances.

    Frame sequence per turn:
      TurnState(running=True) → SessionReady → AiChunk* → AiDone → TurnState(running=False)
      AiError (+ TurnState false) on failure
    """
    out_q = _cursor_out_queues.setdefault(name, asyncio.Queue())
    turn_q = _cursor_turn_queues.setdefault(name, asyncio.Queue())
    _cursor_last_msg_at[name] = datetime.now()

    # B4: tell the user this turn is queued behind others instead of it just
    # silently sitting in turn_q with no visible sign anything happened.
    ahead = turn_q.qsize() + (1 if _cursor_running.get(name, False) else 0)
    await turn_q.put(_CursorTurn(prompt, prior_session_id, cwd, mode, model))
    if ahead > 0:
        noun = "turn" if ahead == 1 else "turns"
        await out_q.put(AgentActivity(session=name, label=f"queued ({ahead} {noun} ahead)"))

    _ensure_cursor_worker(name)
    return out_q
