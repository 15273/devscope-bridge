"""Long-lived `codex app-server` JSON-RPC for steering + sandbox approvals."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from devscope_bridge import cursor_watchdog
from devscope_bridge import session_store
from devscope_bridge.models import (
    AgentActivity,
    AiChunk,
    AiDone,
    AiError,
    PermissionOption,
    PermissionRequest,
    SessionReady,
    TurnState,
)
from devscope_bridge.session_manager_codex import resolve_codex_bin
from devscope_bridge.session_runtime import subscription_env

logger = logging.getLogger(__name__)


def app_server_available() -> bool:
    if os.environ.get("DEVSCOPE_CODEX_EXEC_ONLY") == "1":
        return False
    return bool(resolve_codex_bin())


@dataclass
class _AppSession:
    name: str
    proc: asyncio.subprocess.Process
    reader_task: asyncio.Task
    out_queue: asyncio.Queue
    cwd: str
    thread_id: str | None = None
    turn_id: str | None = None
    pending: dict[int, asyncio.Future] = field(default_factory=dict)
    next_id: int = 1
    turn_running: bool = False
    last_msg_at: datetime = field(default_factory=datetime.now)
    pending_approvals: dict[str, int] = field(default_factory=dict)
    handshake_done: bool = False
    agent_text: str = ""


_sessions: dict[str, _AppSession] = {}


def has_session(name: str) -> bool:
    sess = _sessions.get(name)
    return sess is not None and sess.proc.returncode is None


def is_busy(name: str) -> bool:
    sess = _sessions.get(name)
    return bool(sess and sess.turn_running)


def get_out_queue(name: str) -> asyncio.Queue | None:
    sess = _sessions.get(name)
    return sess.out_queue if sess else None


def get_session_state(name: str) -> dict | None:
    sess = _sessions.get(name)
    if sess is None or sess.proc.returncode is not None:
        return None
    entry = session_store.get_session(name)
    return {
        "name": name,
        "agent": "codex",
        "pid": sess.proc.pid,
        "returncode": sess.proc.returncode,
        "turn_done": not sess.turn_running,
        "session_id": sess.thread_id or (entry.get("session_id") if entry else None),
        "mode": entry.get("mode") if entry else None,
        "model": entry.get("model") if entry else None,
        "last_msg_at": sess.last_msg_at.isoformat(),
        "last_output_at": cursor_watchdog.get_last_output_epoch(name),
        "current_tool": cursor_watchdog.get_current_tool(name),
        "turn_elapsed_s": cursor_watchdog.get_turn_elapsed_s(name),
        "queued_turns": 0,
        "awaiting": "tool_blocked" if sess.pending_approvals else None,
    }


def _rpc(method: str, params: dict | None, req_id: int | None) -> dict:
    msg: dict = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        msg["params"] = params
    if req_id is not None:
        msg["id"] = req_id
    return msg


async def _write(sess: _AppSession, payload: dict) -> None:
    assert sess.proc.stdin is not None
    sess.proc.stdin.write((json.dumps(payload) + "\n").encode())
    await sess.proc.stdin.drain()


async def _request(sess: _AppSession, method: str, params: dict | None = None, timeout: float = 30) -> dict:
    req_id = sess.next_id
    sess.next_id += 1
    fut: asyncio.Future = asyncio.get_running_loop().create_future()
    sess.pending[req_id] = fut
    await _write(sess, _rpc(method, params, req_id))
    try:
        return await asyncio.wait_for(fut, timeout=timeout)
    finally:
        sess.pending.pop(req_id, None)


async def _notify(sess: _AppSession, method: str, params: dict | None = None) -> None:
    await _write(sess, _rpc(method, params, None))


def _thread_id_from_result(result: object) -> str | None:
    if not isinstance(result, dict):
        return None
    thread = result.get("thread")
    if isinstance(thread, dict) and isinstance(thread.get("id"), str):
        return thread["id"]
    if isinstance(result.get("threadId"), str):
        return result["threadId"]
    if isinstance(result.get("id"), str):
        return result["id"]
    return None


def _turn_id_from_result(result: object) -> str | None:
    if not isinstance(result, dict):
        return None
    turn = result.get("turn")
    if isinstance(turn, dict) and isinstance(turn.get("id"), str):
        return turn["id"]
    if isinstance(result.get("turnId"), str):
        return result["turnId"]
    return None


async def _handle_server_request(sess: _AppSession, msg: dict) -> None:
    method = str(msg.get("method") or "")
    req_id = msg.get("id")
    params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
    if method in (
        "item/commandExecution/requestApproval",
        "item/fileChange/requestApproval",
    ):
        request_id = str(params.get("approvalId") or params.get("itemId") or uuid.uuid4().hex[:12])
        if isinstance(req_id, int):
            sess.pending_approvals[request_id] = req_id
        command = str(params.get("command") or params.get("reason") or method)
        await sess.out_queue.put(PermissionRequest(
            session=sess.name,
            request_id=request_id,
            kind="tool_blocked",
            title="Codex needs approval",
            description=command[:400],
            tool_name=command[:80],
            options=[
                PermissionOption(id="approve", label="Allow once"),
                PermissionOption(id="allow_once", label="Allow for session"),
                PermissionOption(id="deny", label="Deny"),
            ],
        ))
        return
    if isinstance(req_id, int):
        await _write(sess, {"jsonrpc": "2.0", "id": req_id, "result": {}})


async def _handle_notification(sess: _AppSession, msg: dict) -> None:
    method = str(msg.get("method") or "")
    params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
    cursor_watchdog.touch_stdout(sess.name)

    if method in ("thread/started",):
        tid = _thread_id_from_result(params)
        if tid:
            sess.thread_id = tid
            session_store.upsert_session(sess.name, tid)
            await sess.out_queue.put(SessionReady(
                session=sess.name, session_id=tid, resumed=True,
            ))
        return

    if method == "turn/started":
        sess.turn_running = True
        sess.agent_text = ""
        turn = params.get("turn") if isinstance(params.get("turn"), dict) else {}
        if isinstance(turn.get("id"), str):
            sess.turn_id = turn["id"]
        return

    if method in ("item/agentMessage/delta",):
        delta = params.get("delta") or params.get("text")
        if delta:
            text = str(delta)
            sess.agent_text += text
            await sess.out_queue.put(AiChunk(session=sess.name, text=text))
        return

    if method in ("item/started", "item/completed"):
        item = params.get("item") if isinstance(params.get("item"), dict) else params
        kind = str(item.get("type") or "")
        if kind in ("commandExecution", "command_execution", "fileChange", "file_change", "mcpToolCall"):
            label = str(item.get("command") or item.get("name") or kind)
            status = "running" if method == "item/started" else "done"
            if item.get("status") in ("failed", "declined"):
                status = "error"
            cursor_watchdog.set_current_tool(sess.name, kind if status == "running" else None)
            await sess.out_queue.put(AgentActivity(
                session=sess.name, label=label, tool=kind, status=status,
            ))
        if method == "item/completed" and kind in ("agentMessage", "agent_message"):
            text = item.get("text")
            if isinstance(text, str) and text:
                suffix = text[len(sess.agent_text):] if text.startswith(sess.agent_text) else text
                if suffix:
                    await sess.out_queue.put(AiChunk(session=sess.name, text=suffix))
                sess.agent_text = text
        return

    if method == "turn/completed":
        turn = params.get("turn") if isinstance(params.get("turn"), dict) else {}
        status = str(turn.get("status") or "completed")
        sess.turn_running = False
        sess.turn_id = None
        cursor_watchdog.end_turn(sess.name)
        if status in ("failed", "error"):
            err = turn.get("error") or "turn failed"
            await sess.out_queue.put(AiError(session=sess.name, exit_code=-1, stderr_tail=str(err)))
        else:
            await sess.out_queue.put(AiDone(session=sess.name, exit_code=0))
        await sess.out_queue.put(TurnState(session=sess.name, running=False))


async def _reader(sess: _AppSession) -> None:
    assert sess.proc.stdout is not None
    try:
        while True:
            line = await sess.proc.stdout.readline()
            if not line:
                break
            raw = line.decode("utf-8", errors="replace").strip()
            if not raw:
                continue
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(msg, dict):
                continue
            if "id" in msg and ("result" in msg or "error" in msg):
                fut = sess.pending.get(msg["id"])
                if fut and not fut.done():
                    if "error" in msg:
                        fut.set_exception(RuntimeError(str(msg["error"])))
                    else:
                        fut.set_result(msg.get("result") or {})
                continue
            if "id" in msg and "method" in msg:
                await _handle_server_request(sess, msg)
                continue
            if "method" in msg:
                await _handle_notification(sess, msg)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("codex app-server reader failed for %s", sess.name)
    finally:
        if sess.turn_running:
            sess.turn_running = False
            await sess.out_queue.put(AiError(
                session=sess.name, exit_code=-1,
                stderr_tail="[bridge] Codex app-server disconnected",
            ))
            await sess.out_queue.put(TurnState(session=sess.name, running=False))


async def _drain_stderr(sess: _AppSession) -> None:
    """Drain diagnostics continuously so the child cannot block on a full pipe."""
    if sess.proc.stderr is None:
        return
    try:
        while await sess.proc.stderr.readline():
            pass
    except (asyncio.CancelledError, OSError):
        return


async def _ensure(name: str, cwd: str) -> _AppSession:
    existing = _sessions.get(name)
    if existing and existing.proc.returncode is None:
        return existing
    binary = resolve_codex_bin()
    if not binary:
        raise FileNotFoundError("codex not found")
    proc = await asyncio.create_subprocess_exec(
        binary, "app-server",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd if os.path.isdir(cwd) else None,
        env=subscription_env(name),
    )
    q = existing.out_queue if existing else asyncio.Queue()
    sess = _AppSession(name=name, proc=proc, reader_task=None, out_queue=q, cwd=cwd)  # type: ignore[arg-type]
    sess.reader_task = asyncio.create_task(_reader(sess))
    asyncio.create_task(_drain_stderr(sess))
    _sessions[name] = sess
    await _request(sess, "initialize", {
        "clientInfo": {"name": "devscope", "title": "DevScope", "version": "0.1"},
    })
    await _notify(sess, "initialized", {})
    sess.handshake_done = True
    return sess


async def dispatch(
    name: str,
    prompt: str,
    prior_session_id: str | None,
    cwd: str,
    mode: str | None = None,
    model: str | None = None,
) -> asyncio.Queue:
    sess = await _ensure(name, cwd)
    sess.last_msg_at = datetime.now()
    sess.cwd = cwd

    if sess.turn_running and sess.thread_id:
        await _request(sess, "turn/steer", {
            "threadId": sess.thread_id,
            "input": [{"type": "text", "text": prompt}],
        })
        return sess.out_queue

    if not sess.thread_id:
        if prior_session_id:
            try:
                result = await _request(sess, "thread/resume", {
                    "threadId": prior_session_id,
                    "cwd": cwd,
                    "excludeTurns": True,
                })
                sess.thread_id = _thread_id_from_result(result) or prior_session_id
            except Exception as exc:
                logger.warning("thread/resume failed (%s) — starting new thread", exc)
        if not sess.thread_id:
            sandbox = "read-only" if mode == "inspect" else "workspace-write"
            params: dict = {"cwd": cwd, "sandbox": sandbox}
            if model:
                params["model"] = model
            result = await _request(sess, "thread/start", params)
            sess.thread_id = _thread_id_from_result(result)
        if sess.thread_id:
            session_store.upsert_session(name, sess.thread_id)
            await sess.out_queue.put(SessionReady(
                session=name, session_id=sess.thread_id,
                resumed=bool(prior_session_id),
            ))

    if not sess.thread_id:
        raise RuntimeError("codex app-server did not return a thread id")

    cursor_watchdog.begin_turn(name)
    await sess.out_queue.put(TurnState(session=name, running=True))
    result = await _request(sess, "turn/start", {
        "threadId": sess.thread_id,
        "input": [{"type": "text", "text": prompt}],
        **({"model": model} if model else {}),
    })
    sess.turn_id = _turn_id_from_result(result)
    sess.turn_running = True
    session_store.append_bridge_turn(name, "user", prompt)
    return sess.out_queue


async def send_approval(name: str, request_id: str, option_id: str) -> bool:
    sess = _sessions.get(name)
    if sess is None:
        return False
    rpc_id = sess.pending_approvals.pop(request_id, None)
    if rpc_id is None:
        return False
    decision = "accept"
    if option_id in ("deny", "skip"):
        decision = "decline"
    elif option_id == "allow_once":
        decision = "acceptForSession"
    await _write(sess, {"jsonrpc": "2.0", "id": rpc_id, "result": {"decision": decision}})
    return True


def interrupt(name: str) -> bool:
    sess = _sessions.get(name)
    if sess is None or not sess.turn_running or not sess.thread_id or not sess.turn_id:
        return False
    asyncio.create_task(_request(sess, "turn/interrupt", {
        "threadId": sess.thread_id,
        "turnId": sess.turn_id,
    }))
    return True


def shutdown(name: str) -> None:
    sess = _sessions.pop(name, None)
    if sess is None:
        return
    if sess.reader_task and not sess.reader_task.done():
        sess.reader_task.cancel()
    if sess.proc.returncode is None:
        try:
            sess.proc.terminate()
        except ProcessLookupError:
            pass
