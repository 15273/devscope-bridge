"""Chat WebSocket: pump, inbound frames, slash commands."""

from __future__ import annotations

import asyncio
import json
import logging
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from devscope_bridge import background_english_coach
from devscope_bridge import browser_relay
from devscope_bridge import session_manager
from devscope_bridge import session_manager_cursor
from devscope_bridge import builtin_commands as _builtins
from devscope_bridge import prompt_templates as _ptemplates
from devscope_bridge.bridge_auth import SESSION_NAME_RE, ws_auth
from devscope_bridge.models import AgentActivity, MsgAck, PermAck, PermissionResponse, UserMsg

logger = logging.getLogger(__name__)

router = APIRouter()

_PROMPT_TEMPLATE_BUILDERS: dict[str, object] = {
    "/review":          _ptemplates.build_review_prompt,
    "/security-review": _ptemplates.build_security_review_prompt,
    "/pr-comments":     _ptemplates.build_pr_comments_prompt,
}

async def _pump_frames(ws: WebSocket, q: asyncio.Queue) -> None:
    """Forward every frame from the session out_queue to the WebSocket.

    Runs for the WS lifetime.  Never breaks on AiDone/AiError — forwards them
    so the UI can close its turn bubble, then waits for the next frame.
    Cancelled by ws_session on disconnect.

    A1 fix: a send failure used to silently DROP the just-popped frame (q.get()
    already removed it) — the reconnecting client would never see it. Now the
    frame is pushed back onto the session's persistent out_queue so the next
    pump (a fresh reconnect) still delivers it, then this pump stops.
    """
    while True:
        frame = await q.get()
        try:
            await ws.send_text(frame.model_dump_json())
        except Exception:
            q.put_nowait(frame)  # requeue — do not drop; next pump will deliver it
            return  # WS gone — exit silently


def _parse_command_target(prompt: str, default: str) -> str:
    """Extract the target session from a `/cmd [session]` command.

    Falls back to `default` (the current session) when no valid name is given.
    """
    parts = prompt.split(maxsplit=1)
    if len(parts) > 1:
        candidate = parts[1].strip()
        if SESSION_NAME_RE.match(candidate):
            return candidate
    return default


def _silence_seconds(target: str) -> float:
    """Real seconds since the target session last produced STDOUT (0.0 if unknown).

    A5/RC-9: uses last_output_at (turn progress), not the old "last_msg_at"
    (time the user's message was dispatched) — conflating the two made /medic
    always report ~0s silence right after a message was sent, even if the
    turn had actually been stuck for minutes.
    """
    state = session_manager.get_session_state(target)
    if not state:
        return 0.0
    last_output_at = state.get("last_output_at")
    if not last_output_at:
        return 0.0
    return max(0.0, time.time() - last_output_at)


def resolve_out_queue(session_name: str) -> asyncio.Queue:
    """Create-or-get the ONE persistent out_queue for this session.

    A1 fix (RC-4): never a throwaway `asyncio.Queue()` — a pump attached to a
    fresh, disconnected queue would never see frames written to the real
    queue once the session actually spawns (the classic "slash-command-first
    then message never arrives" bug). Claude sessions resolve through
    session_manager's own registry (which run_prompt's spawn path also reads
    from — same object guaranteed). Cursor sessions share the SAME dict
    dispatch_cursor() populates via setdefault() (session_manager_cursor.py,
    WS-B owned) — reading through that dict here (not editing that file)
    means whichever side creates the queue first, the other reuses it.
    """
    active = session_manager._sessions.get(session_name)
    if active is not None:
        return active.out_queue
    if session_manager._session_agent(session_name) == "cursor":
        return session_manager_cursor._cursor_out_queues.setdefault(session_name, asyncio.Queue())
    return session_manager.get_or_create_out_queue(session_name)


_resolve_out_queue = resolve_out_queue


# session_name -> the currently-live pump task for that session's WS. Lets a
# fast reconnect cancel the OLD pump instead of leaving two pumps draining
# the same out_queue into two different sockets (one of them stale).
_session_pumps: dict[str, asyncio.Task] = {}


def _start_session_pump(session_name: str, ws: WebSocket, q: asyncio.Queue) -> asyncio.Task:
    old = _session_pumps.get(session_name)
    if old is not None and not old.done():
        old.cancel()
    task = asyncio.create_task(_pump_frames(ws, q))
    _session_pumps[session_name] = task
    return task


def _command_queue(session_name: str, ws: WebSocket, pump_task: asyncio.Task | None):
    """Resolve the out_queue for a session command and ensure a pump is running."""
    q = resolve_out_queue(session_name)
    if pump_task is None or pump_task.done():
        pump_task = _start_session_pump(session_name, ws, q)
    return q, pump_task


async def _handle_session_command(
    ws: WebSocket, session_name: str, verb: str, prompt: str, pump_task: asyncio.Task | None,
) -> asyncio.Task | None:
    """Dispatch /medic, /interrupt, /ask — each on a separate path, never queued."""
    from devscope_bridge import main as bridge_main
    target = _parse_command_target(prompt, session_name)
    q, pump_task = bridge_main._command_queue(session_name, ws, pump_task)

    if verb == "/medic":
        asyncio.ensure_future(bridge_main.watchdog_medic.run_medic(
            target, q, asyncio.Event(),
            elapsed_s=_silence_seconds(target), trigger="manual",
        ))
    elif verb == "/interrupt":
        if session_manager.is_turn_running(target):
            await q.put(AgentActivity(
                session=target, label="⏹ Interrupting…", detail="Stopping the current turn.",
            ))
            session_manager.interrupt_session(target)
        else:
            await q.put(AgentActivity(
                session=target, label="⏹ Nothing to interrupt",
                detail="No turn is currently running.",
            ))
    elif verb == "/ask":
        parts = prompt.split(maxsplit=1)
        question = parts[1] if len(parts) > 1 else ""
        asyncio.ensure_future(
            bridge_main.capability_router.run_on_queue("parallel_ask", question, session_name, q)
        )
    elif verb in ("/cursor-ctx", "/ctx"):
        parts = prompt.split(maxsplit=1)
        task = parts[1] if len(parts) > 1 else ""

        async def _run_cursor_ctx() -> None:
            nonlocal pump_task
            forward_q = await bridge_main.capability_router.run_on_queue(
                "codebase_scout", task, session_name, q,
            )
            if forward_q is not None and forward_q is not q:
                if pump_task is not None and not pump_task.done():
                    pump_task.cancel()
                pump_task = asyncio.create_task(_pump_frames(ws, forward_q))

        asyncio.ensure_future(_run_cursor_ctx())

    elif verb in ("/cursor-task", "/plugins", "/notion"):
        parts = prompt.split(maxsplit=1)
        task = parts[1] if len(parts) > 1 else ""
        asyncio.ensure_future(
            bridge_main.capability_router.run_on_queue("cursor_plugins", task, session_name, q)
        )

    return pump_task


async def _handle_user_msg(
    ws: WebSocket, session_name: str, data: dict, pump_task: asyncio.Task | None,
) -> asyncio.Task | None:
    """Handle one inbound user_msg frame; returns the (possibly updated) pump_task.

    Acks with msg_ack immediately once the message is accepted for processing
    (contract 1 / A8) — before dispatch, so a slow-to-start command still acks
    promptly instead of leaving the panel's optimistic bubble unconfirmed.
    """
    try:
        msg = UserMsg.model_validate(data)
    except Exception:
        msg = UserMsg(text=data.get("text", ""))

    prompt = msg.text.strip()
    if not prompt:
        return pump_task

    if msg.client_msg_id:
        await ws.send_text(MsgAck(client_msg_id=msg.client_msg_id).model_dump_json())

    # Session-control commands run on a SEPARATE process (medic/ask) or act on
    # the live process (interrupt) — never queued to the stuck session's
    # stdin.  Each reports to this WS's out_queue.
    verb = prompt.split(maxsplit=1)[0]
    if verb in ("/medic", "/interrupt", "/ask", "/cursor-ctx", "/ctx", "/cursor-task", "/plugins", "/notion"):
        return await _handle_session_command(ws, session_name, verb, prompt, pump_task)

    # Prompt-template commands — transform verb+args into a curated prompt and
    # run it through the normal run_prompt path so the model answers.
    if verb in _PROMPT_TEMPLATE_BUILDERS:
        parts_pt = prompt.split(maxsplit=1)
        args_pt = parts_pt[1].strip() if len(parts_pt) > 1 else ""
        builder = _PROMPT_TEMPLATE_BUILDERS[verb]
        expanded_prompt = builder(args_pt)  # type: ignore[operator]
        session_manager.reset_idle(session_name)
        q = await session_manager.run_prompt(
            session_name, expanded_prompt,
            mode=msg.mode, model=msg.model, context=msg.context,
        )
        if pump_task is None or pump_task.done():
            pump_task = _start_session_pump(session_name, ws, q)
        return pump_task

    # Bridge-side builtin commands — handled locally, never forwarded to CLI.
    _builtin_verbs = {
        "/usage", "/cost", "/context",
        "/compact", "/new", "/model", "/memory",
        "/status", "/add-dir",
    }
    if verb in _builtin_verbs:
        q, pump_task = _command_queue(session_name, ws, pump_task)
        asyncio.ensure_future(_builtins.dispatch(session_name, verb, prompt, q))
        return pump_task

    session_manager.reset_idle(session_name)
    q = await session_manager.run_prompt(
        session_name, prompt,
        mode=msg.mode, model=msg.model, context=msg.context,
    )
    # Reuse the pump on the session's stable out_queue (Claude + Cursor).
    if pump_task is None or pump_task.done():
        pump_task = _start_session_pump(session_name, ws, q)

    # Fire-and-forget English coach — non-blocking, coding turn unaffected.
    # Skip slash-command verbs (already handled above) and empty prompts.
    if msg.coach_enabled and not verb.startswith("/") and prompt:
        asyncio.ensure_future(
            background_english_coach.run_english_coach(
                session_name, q, prompt, msg.coach_lang, msg.coach_focus,
            )
        )
    return pump_task


async def _handle_permission_response(
    ws: WebSocket, session_name: str, data: dict, pump_task: asyncio.Task | None,
) -> asyncio.Task | None:
    """Handle one inbound permission_response frame; returns the pump_task.

    Acks with perm_ack once send_approval has forwarded the decision to the
    process (contract 1 / A8) — the panel flips a permission card to
    "Decision sent" only on this ack, never optimistically.
    """
    try:
        resp = PermissionResponse.model_validate(data)
    except Exception:
        await ws.send_text(json.dumps({
            "type": "error", "message": "Invalid permission_response frame",
        }))
        return pump_task
    await session_manager.send_approval(
        session_name, resp.request_id, resp.option_id,
        answers=resp.answers, custom_text=resp.custom_text,
    )
    await ws.send_text(PermAck(request_id=resp.request_id).model_dump_json())
    # Ensure the pump is running so the next turn's frames are forwarded.
    if pump_task is None or pump_task.done():
        pump_task = _start_session_pump(session_name, ws, resolve_out_queue(session_name))
    return pump_task


async def _ws_receive_loop(
    ws: WebSocket, session_name: str, pump_task: asyncio.Task | None = None,
) -> None:
    """Handle inbound frames.

    A1: the pump is started by ws_session BEFORE this loop begins (on WS
    accept, bound to the session's persistent out_queue) — this loop only
    re-creates it defensively if it ever dies mid-connection. The old
    "created only on first user_msg" behavior left frames that arrived
    between reconnect and the next message stuck undelivered (RC-4).

    For user_msg: calls run_prompt() (writes to stdin) and returns IMMEDIATELY.
    The pump task drains out_queue independently, so the loop stays unblocked
    and can accept the next message while the current turn is still streaming.
    """
    try:
        while True:
            raw = await ws.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await ws.send_text(json.dumps({"type": "error", "message": "Invalid JSON"}))
                continue

            msg_type = data.get("type")
            if msg_type == "user_msg":
                pump_task = await _handle_user_msg(ws, session_name, data, pump_task)

            elif msg_type == "hello":
                # Extension announces which Chrome profile this WS belongs to,
                # enabling cross-profile tab listing and action routing.
                browser_relay.set_ws_profile(
                    session_name,
                    str(data.get("profile_id", "")),
                    str(data.get("profile_label", "")),
                )

            elif msg_type == "browser_result":
                browser_relay.resolve_browser_result(data)

            elif msg_type == "permission_response":
                pump_task = await _handle_permission_response(ws, session_name, data, pump_task)

            else:
                logger.debug("Unknown WS frame '%s' from '%s'", msg_type, session_name)

    except WebSocketDisconnect:
        logger.info("WS disconnected: session='%s'", session_name)
    finally:
        if pump_task is not None:
            pump_task.cancel()
            if _session_pumps.get(session_name) is pump_task:
                _session_pumps.pop(session_name, None)




@router.websocket("/ws/{session_name}")
async def ws_session(ws: WebSocket, session_name: str) -> None:
    if not SESSION_NAME_RE.match(session_name):
        await ws.close(code=1008, reason="Invalid session name")
        return
    if not await ws_auth(ws):
        await ws.close(code=4003, reason="Forbidden")
        return

    await ws.accept()
    browser_relay.register_ws(session_name, ws)
    # A1: pump attaches HERE, on connect — not lazily on first user_msg — so
    # frames already sitting in the session's persistent out_queue (e.g. from
    # before a reconnect) are delivered immediately, and a slash-command-first
    # WS still sees the real session's frames once it later spawns.
    q = resolve_out_queue(session_name)
    pump_task = _start_session_pump(session_name, ws, q)
    logger.info("WS connected: session='%s'", session_name)
    try:
        await _ws_receive_loop(ws, session_name, pump_task)
    finally:
        browser_relay.deregister_ws(session_name, ws)

