"""PTY WebSocket — interactive terminal, separate from /ws sessions."""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from devscope_bridge import pty_manager
from devscope_bridge.bridge_auth import SESSION_NAME_RE, ws_auth

logger = logging.getLogger(__name__)

router = APIRouter()

async def _pty_output_pump(ws: WebSocket, terminal_id: str, term) -> None:
    """Forward PTY output → ws until EOF (None sentinel)."""
    while True:
        chunk = await term.out_queue.get()
        if chunk is None:
            try:
                await ws.send_text(json.dumps({"type": "pty_exit"}))
            except Exception:
                pass
            return
        pty_manager.ingest_pty_output(terminal_id, chunk)
        try:
            await ws.send_text(json.dumps({"type": "pty_output", "data": chunk}))
        except Exception:
            return


async def _pty_session_loop(
    ws: WebSocket,
    terminal_id: str,
    cmd: str,
    session: str | None,
    pump_holder: list[asyncio.Task | None],
) -> None:
    """Wait for client winsize, spawn PTY, then forward input/resize until disconnect."""
    term = None
    pump_task: asyncio.Task | None = None

    async def ensure_spawned(cols: int, rows: int) -> None:
        nonlocal term, pump_task
        if term is not None:
            pty_manager.resize(terminal_id, cols, rows)
            return
        term = await pty_manager.open_terminal(
            terminal_id, cmd, session, cols=cols, rows=rows,
        )
        pump_task = asyncio.create_task(_pty_output_pump(ws, terminal_id, term))
        pump_holder[0] = pump_task

    loop = asyncio.get_running_loop()
    deadline = loop.time() + 3.0
    while term is None:
        remaining = deadline - loop.time()
        if remaining <= 0:
            await ensure_spawned(pty_manager._FALLBACK_COLS, pty_manager._FALLBACK_ROWS)
            break
        try:
            raw = await asyncio.wait_for(ws.receive_text(), timeout=remaining)
        except asyncio.TimeoutError:
            await ensure_spawned(pty_manager._FALLBACK_COLS, pty_manager._FALLBACK_ROWS)
            break
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if data.get("type") == "pty_resize":
            await ensure_spawned(
                int(data.get("cols", pty_manager._FALLBACK_COLS)),
                int(data.get("rows", pty_manager._FALLBACK_ROWS)),
            )
            break

    while True:
        raw = await ws.receive_text()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        mtype = data.get("type")
        if mtype == "pty_input":
            pty_manager.write_input(terminal_id, data.get("data", ""))
        elif mtype == "pty_resize":
            cols = int(data.get("cols", pty_manager._FALLBACK_COLS))
            rows = int(data.get("rows", pty_manager._FALLBACK_ROWS))
            if term is None:
                await ensure_spawned(cols, rows)
            else:
                pty_manager.resize(terminal_id, cols, rows)


@router.websocket("/pty/{terminal_id}")
async def pty_terminal(ws: WebSocket, terminal_id: str) -> None:
    """Real interactive terminal (PTY) — additive, separate from /ws sessions.

    Query params: cmd ("resume"|"claude"|"shell"), session (name, for --resume).
    """
    if not SESSION_NAME_RE.match(terminal_id):
        await ws.close(code=1008, reason="Invalid terminal id")
        return
    if not await ws_auth(ws):
        await ws.close(code=4003, reason="Forbidden")
        return

    await ws.accept()
    cmd = ws.query_params.get("cmd", "resume")
    session = ws.query_params.get("session") or None
    cmd, session = pty_manager.resolve_terminal_params(terminal_id, cmd, session)
    logger.info("PTY WS connected: terminal='%s' cmd='%s' session='%s'", terminal_id, cmd, session)
    pump_holder: list[asyncio.Task | None] = [None]
    try:
        await _pty_session_loop(ws, terminal_id, cmd, session, pump_holder)
    except WebSocketDisconnect:
        logger.info("PTY WS disconnected: terminal='%s'", terminal_id)
    except Exception as exc:  # noqa: BLE001 — report spawn failure to the panel
        try:
            await ws.send_text(json.dumps({"type": "pty_error", "message": str(exc)}))
        except Exception:
            pass
        await ws.close()
        return
    finally:
        pump_task = pump_holder[0]
        if pump_task is not None:
            pump_task.cancel()
        pty_manager.close_terminal(terminal_id)

