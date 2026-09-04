"""Shared one-shot CLI turn queue (Codex exec, Antigravity agy).

Cursor stays on session_manager_cursor. New agents plug in via OneShotBackend.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import select
import signal
import subprocess
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from devscope_bridge import cursor_watchdog
from devscope_bridge import session_store
from devscope_bridge.models import AgentActivity, AiChunk, AiDone, AiError, SessionReady, TurnState
from devscope_bridge.session_runtime import subscription_env

logger = logging.getLogger(__name__)

_STDERR_TAIL_LINES = 80


class OneShotBackend(Protocol):
    agent: str

    def resolve_bin(self) -> str | None: ...
    def missing_bin_message(self) -> str: ...
    def build_cmd(
        self,
        binary: str,
        prompt: str,
        prior_session_id: str | None,
        mode: str | None,
        model: str | None,
        cwd: str,
    ) -> list[str]: ...
    def parse_line(self, line: str, accum: str) -> tuple[str | None, str, str | None]: ...
    def activities_from_obj(self, obj: dict) -> list[tuple[str, str, str | None, str | None]]: ...
    def env(self, session_name: str, cwd: str) -> dict[str, str]: ...
    def capture_before(self, cwd: str) -> Any: ...
    def recover_session_id(
        self,
        capture: Any,
        stdout_lines: list[str],
        stderr: str,
        cwd: str,
    ) -> str | None: ...


@dataclass
class _Turn:
    prompt: str
    prior_session_id: str | None
    cwd: str
    mode: str | None
    model: str | None
    backend: OneShotBackend


_out_queues: dict[str, asyncio.Queue] = {}
_turn_queues: dict[str, asyncio.Queue] = {}
_workers: dict[str, asyncio.Task] = {}
_running: dict[str, bool] = {}
_current_proc: dict[str, subprocess.Popen] = {}
_last_msg_at: dict[str, datetime] = {}
_backends: dict[str, OneShotBackend] = {}


def get_out_queue(name: str) -> asyncio.Queue | None:
    return _out_queues.get(name)


def ensure_out_queue(name: str) -> asyncio.Queue:
    return _out_queues.setdefault(name, asyncio.Queue())


def is_busy(name: str) -> bool:
    if _running.get(name):
        return True
    q = _turn_queues.get(name)
    return q is not None and not q.empty()


def get_session_state(name: str) -> dict | None:
    running = _running.get(name, False)
    proc = _current_proc.get(name)
    turn_q = _turn_queues.get(name)
    queued = turn_q.qsize() if turn_q is not None else 0
    if not running and queued == 0 and (proc is None or proc.poll() is not None):
        return None
    entry = session_store.get_session(name)
    last_msg_at = _last_msg_at.get(name)
    backend = _backends.get(name)
    return {
        "name": name,
        "agent": backend.agent if backend else (entry.get("agent") if entry else None),
        "pid": proc.pid if proc is not None else None,
        "returncode": proc.poll() if proc is not None else None,
        "turn_done": not running and queued == 0,
        "pending_turns": queued,
        "session_id": entry.get("session_id") if entry else None,
        "mode": entry.get("mode") if entry else None,
        "model": entry.get("model") if entry else None,
        "last_msg_at": last_msg_at.isoformat() if last_msg_at else None,
        "last_output_at": cursor_watchdog.get_last_output_epoch(name),
        "current_tool": cursor_watchdog.get_current_tool(name),
        "turn_elapsed_s": cursor_watchdog.get_turn_elapsed_s(name),
        "queued_turns": queued,
        "awaiting": None,
    }


def interrupt(name: str) -> bool:
    proc = _current_proc.get(name)
    running = _running.get(name, False)
    pending = bool(_turn_queues.get(name) and not _turn_queues[name].empty())
    if not running and not pending and (proc is None or proc.poll() is not None):
        return False
    cancelled = _drain_queued(name)
    if cancelled:
        out_q = _out_queues.get(name)
        if out_q is not None:
            out_q.put_nowait(AgentActivity(
                session=name, label=f"Stopped — {cancelled} queued turn(s) cancelled",
            ))
    if proc is not None and proc.poll() is None:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        return True
    return running or pending


def shutdown(name: str) -> None:
    proc = _current_proc.pop(name, None)
    if proc is not None and proc.poll() is None:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
    _running.pop(name, None)
    _turn_queues.pop(name, None)
    _out_queues.pop(name, None)
    _last_msg_at.pop(name, None)
    _backends.pop(name, None)
    task = _workers.pop(name, None)
    if task is not None and not task.done():
        task.cancel()


def _drain_queued(name: str) -> int:
    turn_q = _turn_queues.get(name)
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


def default_env(session_name: str, cwd: str) -> dict[str, str]:
    return subscription_env(session_name)


def _iter_stdout_lines(proc: subprocess.Popen):
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
    buf: deque = deque(maxlen=_STDERR_TAIL_LINES)

    def _drain() -> None:
        assert proc.stderr is not None
        try:
            for line in proc.stderr:
                buf.append(line)
        except (ValueError, OSError):
            pass

    threading.Thread(target=_drain, daemon=True, name="oneshot-stderr").start()
    return buf


def _run_blocking(
    turn: _Turn,
    loop: asyncio.AbstractEventLoop,
    q: asyncio.Queue,
    session_name: str,
) -> None:
    backend = turn.backend
    binary = backend.resolve_bin()
    if not binary:
        raise FileNotFoundError(backend.missing_bin_message())

    cmd = backend.build_cmd(
        binary, turn.prompt, turn.prior_session_id, turn.mode, turn.model, turn.cwd,
    )
    capture = backend.capture_before(turn.cwd)
    logger.info("oneshot %s session=%s cmd0=%s", backend.agent, session_name, cmd[0])

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=turn.cwd if os.path.isdir(turn.cwd) else None,
        env=backend.env(session_name, turn.cwd),
    )
    _current_proc[session_name] = proc
    stderr_buf = _spawn_stderr_drain(proc)

    stdout_lines: list[str] = []
    accum = ""
    resolved_sid = turn.prior_session_id
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
                if isinstance(obj, dict):
                    for label, tool, detail, status in backend.activities_from_obj(obj):
                        if status == "running":
                            cursor_watchdog.set_current_tool(session_name, tool)
                        elif status in ("done", "error"):
                            cursor_watchdog.set_current_tool(session_name, None)
                        _put(AgentActivity(
                            session=session_name, label=label, tool=tool,
                            detail=detail, status=status,
                        ))
            except json.JSONDecodeError:
                pass
        delta, accum, sid_line = backend.parse_line(line, accum)
        if sid_line:
            resolved_sid = sid_line
        if not session_ready_sent and resolved_sid:
            session_store.upsert_session(session_name, resolved_sid)
            _put(SessionReady(
                session=session_name, session_id=resolved_sid,
                resumed=bool(turn.prior_session_id),
            ))
            session_ready_sent = True
        if delta:
            _put(AiChunk(session=session_name, text=delta))
            emitted_any = True

    try:
        proc.wait(timeout=60)
    finally:
        _current_proc.pop(session_name, None)

    stderr_out = "".join(stderr_buf)
    recovered = backend.recover_session_id(capture, stdout_lines, stderr_out, turn.cwd)
    if recovered:
        resolved_sid = recovered

    kill_reason = cursor_watchdog.consume_kill_reason(session_name)
    if kill_reason:
        _put(AiError(session=session_name, exit_code=-1, stderr_tail=kill_reason))
        _put(TurnState(session=session_name, running=False))
        return

    if not session_ready_sent:
        new_sid = resolved_sid or turn.prior_session_id or ""
        if new_sid:
            session_store.upsert_session(session_name, new_sid)
            _put(SessionReady(
                session=session_name, session_id=new_sid,
                resumed=bool(turn.prior_session_id),
            ))

    if proc.returncode not in (0, None):
        if proc.returncode is not None and proc.returncode < 0:
            sig = -proc.returncode
            try:
                tail = f"[bridge] Turn stopped ({signal.Signals(sig).name})"
            except (ValueError, AttributeError):
                tail = f"[bridge] Turn stopped (signal {sig})"
        else:
            tail = stderr_out[-500:] or (stdout_lines[-1] if stdout_lines else "nonzero exit")
        _put(AiError(session=session_name, exit_code=proc.returncode or -1, stderr_tail=tail))
        _put(TurnState(session=session_name, running=False))
        return

    if not emitted_any:
        raw = "\n".join(stdout_lines).strip()
        if raw:
            _put(AiChunk(session=session_name, text=raw))
            accum = raw
            emitted_any = True
        else:
            tail = stderr_out[-500:].strip() or f"{backend.agent} returned no output"
            _put(AiError(session=session_name, exit_code=0, stderr_tail=tail))
            _put(TurnState(session=session_name, running=False))
            return

    if accum.strip():
        session_store.append_bridge_turn(session_name, "assistant", accum)
    _put(AiDone(session=session_name, exit_code=0))
    _put(TurnState(session=session_name, running=False))


def _ensure_worker(name: str) -> None:
    task = _workers.get(name)
    if task is not None and not task.done():
        return
    _workers[name] = asyncio.create_task(_worker(name))


async def _worker(name: str) -> None:
    out_q = _out_queues[name]
    turn_q = _turn_queues[name]
    loop = asyncio.get_running_loop()
    while True:
        turn: _Turn = await turn_q.get()
        _running[name] = True
        cursor_watchdog.begin_turn(name)
        medic_active = asyncio.Event()
        wd_task = asyncio.create_task(
            cursor_watchdog.run(
                name,
                out_q,
                is_running=lambda: _running.get(name, False),
                kill_proc=lambda: _kill_proc(name),
                medic_active=medic_active,
            ),
        )
        await out_q.put(TurnState(session=name, running=True))
        try:
            await asyncio.to_thread(_run_blocking, turn, loop, out_q, name)
        except FileNotFoundError as exc:
            await out_q.put(AiError(session=name, exit_code=-1, stderr_tail=str(exc)))
            await out_q.put(TurnState(session=name, running=False))
        except Exception as exc:
            await out_q.put(AiError(session=name, exit_code=-1, stderr_tail=str(exc)))
            await out_q.put(TurnState(session=name, running=False))
        finally:
            _running[name] = False
            cursor_watchdog.end_turn(name)
            wd_task.cancel()
            try:
                await wd_task
            except asyncio.CancelledError:
                pass


def _kill_proc(name: str) -> None:
    proc = _current_proc.get(name)
    if proc is not None and proc.poll() is None:
        try:
            proc.kill()
        except ProcessLookupError:
            pass


async def dispatch(
    name: str,
    prompt: str,
    prior_session_id: str | None,
    cwd: str,
    backend: OneShotBackend,
    mode: str | None = None,
    model: str | None = None,
) -> asyncio.Queue:
    out_q = _out_queues.setdefault(name, asyncio.Queue())
    turn_q = _turn_queues.setdefault(name, asyncio.Queue())
    _last_msg_at[name] = datetime.now()
    _backends[name] = backend
    ahead = turn_q.qsize() + (1 if _running.get(name, False) else 0)
    await turn_q.put(_Turn(prompt, prior_session_id, cwd, mode, model, backend))
    if ahead > 0:
        noun = "turn" if ahead == 1 else "turns"
        await out_q.put(AgentActivity(session=name, label=f"queued ({ahead} {noun} ahead)"))
    _ensure_worker(name)
    return out_q
