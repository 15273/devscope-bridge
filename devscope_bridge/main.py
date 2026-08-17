"""
main.py — Dev Bridge FastAPI application.

Provides:
- WebSocket /ws/{session_name} for streaming Claude CLI output.
- REST: /health, /sessions, /sessions/{name}, /commands, /actions.
- Token auth written to ~/.dev-bridge/token at startup.
- Binds exclusively to 127.0.0.1:7878.

Pump architecture (mid-turn steering)
--------------------------------------
Each WS connection has ONE persistent "pump" task that drains the session's
out_queue → ws.send_text() for the WS lifetime.  The pump never breaks on
AiDone/AiError — it forwards them and keeps running.

_ws_receive_loop calls run_prompt() (writes to stdin) and returns immediately.
The user can send MSG2 while MSG1 is streaming; the CLI queues it in its stdin
pipe and delivers it as a separate turn once MSG1's result event appears.
Queue stability: run_prompt() guarantees the same asyncio.Queue across
respawns, so the pump reference stays valid.
"""

import asyncio
import json
import logging
import os
import re
import secrets
import stat
import sys
import time
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path

from devscope_bridge.local_env import load_local_env

load_local_env()

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from devscope_bridge import session_manager, session_store, session_reader, compact_service
from devscope_bridge import session_manager_cursor
from devscope_bridge import browser_relay
from devscope_bridge import quota_service
from devscope_bridge import oauth_usage_service
from devscope_bridge import usage_audit
from devscope_bridge import watchdog_medic
from devscope_bridge import background_english_coach
from devscope_bridge import capability_router
from devscope_bridge import pty_manager
from devscope_bridge.commands_scanner import scan_commands
from devscope_bridge.agents_scanner import scan_agents
from devscope_bridge.models import (
    AgentActivity,
    HealthResponse, MsgAck, OpenPathRequest, PermAck, PermissionResponse,
    SessionCreateRequest, SessionInfo, SessionsResponse, UserMsg,
)
from devscope_bridge import builtin_commands as _builtins
from devscope_bridge import prompt_templates as _ptemplates

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Prompt-template commands
# ─────────────────────────────────────────────
# These verbs are transformed into curated prompts and run through the normal
# run_prompt path so the model streams a real answer in the session's cwd
# where git / gh are available.  The builder receives the args string (everything
# after the verb) and returns the full prompt to send.
_PROMPT_TEMPLATE_BUILDERS: dict[str, object] = {
    "/review":          _ptemplates.build_review_prompt,
    "/security-review": _ptemplates.build_security_review_prompt,
    "/pr-comments":     _ptemplates.build_pr_comments_prompt,
}

BRIDGE_DIR = Path.home() / ".dev-bridge"
TOKEN_FILE = BRIDGE_DIR / "token"
SESSION_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")

_startup_token: str = ""
_start_time: float = 0.0

# Aliases for tests that patch these directly on this module
_active_ws = browser_relay._active_ws
_pending_actions = browser_relay._pending_actions


# ─────────────────────────────────────────────
# Startup / shutdown
# ─────────────────────────────────────────────

def _generate_and_persist_token() -> str:
    """Reuse the existing token if present, else generate + persist a new one.

    Reusing across restarts means the extension's saved token keeps working —
    no need to re-paste it every time the bridge is restarted.
    """
    BRIDGE_DIR.mkdir(parents=True, exist_ok=True)
    if TOKEN_FILE.exists():
        existing = TOKEN_FILE.read_text().strip()
        if existing:
            return existing
    token = secrets.token_hex(32)
    TOKEN_FILE.write_text(token)
    TOKEN_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return token


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _startup_token, _start_time
    _startup_token = _generate_and_persist_token()
    _start_time = time.time()
    from devscope_bridge import task_store
    task_store.init_db()
    cleared = session_store.repair_duplicate_session_ids()
    if cleared:
        logger.info("Repaired duplicate session_ids: %s", cleared)
    from devscope_bridge import orchestrator
    from devscope_bridge.session_runner import BridgeSessionRunner
    if os.environ.get("ORCHESTRATOR_ENABLED", "1") == "1":
        orchestrator.start_loop(BridgeSessionRunner())
        logger.info("orchestrator loop enabled")
    from devscope_bridge import session_hygiene
    session_hygiene.start_background_loop()
    logger.info("session hygiene loop enabled")
    asyncio.create_task(session_hygiene.run_hygiene_pass())
    session_manager.start_stale_turn_sweeper()
    from devscope_bridge.whatsapp import cockpit_poller
    poller_task = asyncio.create_task(cockpit_poller.run_forever())
    logger.info("cockpit poller started")
    from devscope_bridge.meta_ads import meta_ads_poller
    meta_poller_task = asyncio.create_task(meta_ads_poller.run_forever())
    logger.info("meta ads poller started")
    print(f"\nDev Bridge started. Token: {_startup_token}\n")
    logger.info("Dev Bridge ready on 127.0.0.1:7878")
    yield
    logger.info("Dev Bridge shutting down")
    poller_task.cancel()
    meta_poller_task.cancel()
    from devscope_bridge import orchestrator, session_hygiene
    await orchestrator.stop_loop()
    await session_hygiene.stop_background_loop()
    await session_manager.stop_stale_turn_sweeper()


# ─────────────────────────────────────────────
# App + CORS
# ─────────────────────────────────────────────

_extension_id = os.environ.get("BRIDGE_EXTENSION_ID", "chrome-extension://EXTENSION_ID_PLACEHOLDER")
_cors_origins = [_extension_id, "http://localhost", "http://127.0.0.1"]

app = FastAPI(title="Dev Bridge", version="0.1", lifespan=lifespan, docs_url=None, redoc_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

# ─────────────────────────────────────────────
# Auth helpers
# ─────────────────────────────────────────────

def _extract_token(request: Request) -> str | None:
    qs = request.query_params.get("token")
    if qs:
        return qs
    auth = request.headers.get("Authorization", "")
    return auth[7:] if auth.startswith("Bearer ") else None


def _check_auth(request: Request) -> None:
    if _extract_token(request) != _startup_token:
        client = request.client.host if request.client else "unknown"
        logger.warning("Auth mismatch from %s", client)
        raise HTTPException(status_code=403, detail="Invalid token")


def require_auth(request: Request) -> None:
    _check_auth(request)


from devscope_bridge import task_routes
from devscope_bridge import orchestrator_routes
app.include_router(task_routes.router, dependencies=[Depends(require_auth)])
app.include_router(orchestrator_routes.router, dependencies=[Depends(require_auth)])

from devscope_bridge.schedule_routes import router as schedule_router
app.include_router(schedule_router, dependencies=[Depends(require_auth)])

from devscope_bridge.whatsapp_routes import router as wa_router
app.include_router(wa_router, dependencies=[Depends(require_auth)])

from devscope_bridge.whatsapp.cockpit_routes import router as cockpit_router
app.include_router(cockpit_router, dependencies=[Depends(require_auth)])

from devscope_bridge.gmail_routes import router as gm_router
app.include_router(gm_router, dependencies=[Depends(require_auth)])

from devscope_bridge.calendar_routes import router as cal_router
app.include_router(cal_router, dependencies=[Depends(require_auth)])

from devscope_bridge.meta_ads_routes import router as meta_router
app.include_router(meta_router, dependencies=[Depends(require_auth)])

from devscope_bridge.invoke_routes import router as invoke_router
app.include_router(invoke_router, dependencies=[Depends(require_auth)])

from devscope_bridge.employee_routes import router as employee_router
app.include_router(employee_router, dependencies=[Depends(require_auth)])

from devscope_bridge.plugin_store_routes import router as store_router
app.include_router(store_router, dependencies=[Depends(require_auth)])

from devscope_bridge.fs_routes import router as fs_router
app.include_router(fs_router, dependencies=[Depends(require_auth)])

from devscope_bridge.recording_routes import router as recording_router
app.include_router(recording_router, dependencies=[Depends(require_auth)])


def _validate_session_name(name: str) -> str:
    if not SESSION_NAME_RE.match(name):
        raise HTTPException(status_code=422, detail="Invalid session name")
    return name


# ─────────────────────────────────────────────
# REST endpoints
# ─────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(ok=True, version="0.1", uptime_s=int(time.time() - _start_time))


@app.get("/capabilities")
async def get_capabilities(auth: None = Depends(require_auth)) -> dict:
    """DevScope MCP + OAuth readiness for the extension Settings panel."""
    from devscope_bridge import capability_registry
    from devscope_bridge.capabilities import build_capabilities

    caps = build_capabilities()
    caps["capabilities"] = await capability_registry.list_capabilities()
    return caps


_VALID_AGENTS = {"claude", "cursor"}


def _liveness_fields(name: str) -> dict:
    """Contract-2 liveness fields for one session, read defensively via .get()
    so this works whether the state dict comes from session_manager (Claude)
    or session_manager_cursor (Cursor) — and before/after WS-B finishes wiring
    its own keys. `pending_turns` is Cursor's current key name for the same
    concept as `queued_turns`; both are checked until they're unified."""
    state = session_manager.get_session_state(name) or {}
    return {
        "last_output_at": state.get("last_output_at"),
        "current_tool": state.get("current_tool"),
        "turn_elapsed_s": state.get("turn_elapsed_s"),
        "queued_turns": state.get("queued_turns") or state.get("pending_turns") or 0,
        "awaiting": state.get("awaiting"),
    }


@app.get("/sessions", response_model=SessionsResponse)
async def list_sessions(auth: None = Depends(require_auth)) -> SessionsResponse:
    stored = session_store.load_sessions()
    result: dict[str, SessionInfo] = {}
    for name, entry in stored.items():
        result[name] = SessionInfo(
            session_id=entry["session_id"],
            created_at=entry["created_at"],
            last_used=entry["last_used"],
            active=session_manager.is_active(name),
            turn_running=session_manager.is_turn_running(name),
            agent=entry.get("agent"),
            cwd=entry.get("cwd"),
            mode=entry.get("mode"),
            model=entry.get("model"),
            claude_agent=entry.get("claude_agent"),
            purpose=entry.get("purpose", "chat"),
            **_liveness_fields(name),
        )
    return SessionsResponse(sessions=result)


@app.post("/sessions", status_code=201)
async def create_session(
    body: SessionCreateRequest,
    auth: None = Depends(require_auth),
) -> SessionInfo:
    """Register a new session with agent and cwd metadata. Does not spawn anything."""
    if not SESSION_NAME_RE.match(body.name):
        raise HTTPException(status_code=422, detail="Invalid session name")
    if body.agent not in _VALID_AGENTS:
        raise HTTPException(status_code=422, detail=f"agent must be one of {sorted(_VALID_AGENTS)}")
    if not os.path.isabs(body.cwd):
        raise HTTPException(status_code=422, detail="cwd must be an absolute path")
    if not os.path.isdir(body.cwd):
        raise HTTPException(status_code=422, detail="cwd does not exist or is not a directory")
    if session_store.get_session(body.name) is not None:
        raise HTTPException(status_code=409, detail="Session name already exists")

    entry = session_store.create_session_metadata(
        body.name, body.agent, body.cwd, mode=body.mode, model=body.model,
        purpose=body.purpose,
    )
    return SessionInfo(
        session_id=entry["session_id"],
        created_at=entry["created_at"],
        last_used=entry["last_used"],
        active=False,
        agent=entry["agent"],
        cwd=entry["cwd"],
        mode=entry.get("mode"),
        model=entry.get("model"),
        purpose=entry.get("purpose", "chat"),
    )


@app.delete("/sessions/{name}", status_code=204)
async def delete_session(name: str, auth: None = Depends(require_auth)) -> None:
    name = _validate_session_name(name)
    await session_manager.kill_session(name)
    session_store.delete_session(name)
    # A1: only forget the persistent out_queue on a FULL delete — kill_session
    # alone (reset/respawn/PTY handoff) must keep it so an already-attached WS
    # pump stays valid.
    session_manager.forget_out_queue(name)


@app.post("/sessions/{name}/interrupt", status_code=204)
async def interrupt_session_endpoint(name: str, auth: None = Depends(require_auth)) -> None:
    name = _validate_session_name(name)
    if not session_manager.interrupt_session(name):
        raise HTTPException(status_code=404, detail="No active subprocess for this session")


@app.post("/sessions/{name}/reset", status_code=204)
async def reset_session_endpoint(name: str, auth: None = Depends(require_auth)) -> None:
    """Kill a hung subprocess without deleting session metadata.

    Claude: clear session_id when resume would replay a broken turn.
    Cursor: keep chatId so --resume continues the thread.
    """
    name = _validate_session_name(name)
    entry = session_store.get_session(name)
    if entry is None:
        raise HTTPException(status_code=404, detail="Session not found")
    agent = entry.get("agent", "claude")
    await session_manager.kill_session(name)
    if agent != "cursor":
        session_store.clear_session_id(name)


class SessionCompactRequest(BaseModel):
    extra: str = ""


class SessionModelRequest(BaseModel):
    model: str | None = None


class SessionClaudeAgentRequest(BaseModel):
    claude_agent: str | None = None


@app.post("/sessions/{name}/model")
async def set_session_model_endpoint(
    name: str,
    body: SessionModelRequest,
    auth: None = Depends(require_auth),
) -> dict:
    """Set or clear the Claude model for a session (no chat turn)."""
    name = _validate_session_name(name)
    if session_store.get_session(name) is None:
        raise HTTPException(status_code=404, detail="Session not found")
    model = body.model.strip() if body.model else None
    applied = _builtins.apply_session_model(name, model)
    return {"ok": True, "model": applied}


@app.post("/sessions/{name}/claude-agent")
async def set_session_claude_agent_endpoint(
    name: str,
    body: SessionClaudeAgentRequest,
    auth: None = Depends(require_auth),
) -> dict:
    """Set or clear the Claude subagent (--agent) for a session (no chat turn)."""
    name = _validate_session_name(name)
    if session_store.get_session(name) is None:
        raise HTTPException(status_code=404, detail="Session not found")
    slug = body.claude_agent.strip() if body.claude_agent else None
    if slug:
        known = {a["name"] for a in scan_agents()}
        if known and slug not in known:
            raise HTTPException(status_code=422, detail=f"Unknown claude agent: {slug}")
    applied = _builtins.apply_session_claude_agent(name, slug)
    return {"ok": True, "claude_agent": applied}


@app.post("/sessions/{name}/compact")
async def compact_session_endpoint(
    name: str,
    body: SessionCompactRequest = SessionCompactRequest(),
    auth: None = Depends(require_auth),
) -> dict:
    """Summarize the session transcript and stash preamble for the next user message.

    A7: serialized with the /compact slash command and auto-compact via the
    shared compact_service.guarded_compact lock. A concurrent compact or a
    summarizer failure on a real transcript returns ok:false and leaves the
    session untouched (no clear_session_id / kill_session / transcript reset).
    """
    name = _validate_session_name(name)
    q = _resolve_out_queue(name)
    result = await compact_service.guarded_compact(name, body.extra, q)
    if not result.ok:
        return {"ok": False, "error": result.skipped}
    await compact_service.apply_compact_reset(name, result.preamble, result.was_real_summary)
    return {"ok": True, "was_real_summary": result.was_real_summary}


@app.get("/sessions/{name}/pending")
async def get_pending_endpoint(name: str, auth: None = Depends(require_auth)) -> dict:
    """Unresolved interactive requests for a session (contract 3 / A2).

    Lets a panel that was closed, reloaded, or disconnected while a
    PermissionRequest (plan / ask_user / tool_blocked) was pending recover
    the card on reopen instead of losing it silently.
    """
    name = _validate_session_name(name)
    return {"pending": session_reader.get_pending_permissions(name)}


@app.get("/commands")
async def list_commands(auth: None = Depends(require_auth)) -> dict:
    """List available slash commands from project + user .claude dirs."""
    return {"commands": scan_commands()}


@app.get("/claude-agents")
async def list_claude_agents(auth: None = Depends(require_auth)) -> dict:
    """List Claude Code subagents from .claude/agents/*.md."""
    return {"agents": scan_agents()}


@app.get("/quota")
async def get_quota(auth: None = Depends(require_auth)) -> dict:
    """Claude usage for the panel's global battery + usage detail window.

    Merges two local sources: ccusage (current 5h block tokens/cost) and the
    official `/api/oauth/usage` limits (5h + weekly utilization %). Each source
    degrades independently; returns {available: False} only when ccusage has no
    active block.
    """
    quota, usage = await asyncio.gather(
        quota_service.get_quota(),
        oauth_usage_service.get_usage(),
    )
    if usage.get("available"):
        quota = {**quota, "available": True,
                 "limits": usage["limits"], "extra_usage": usage["extra_usage"]}
    return quota


@app.get("/usage/audit")
async def get_usage_audit(auth: None = Depends(require_auth)) -> dict:
    """Deep token burn diagnosis: active block, top sessions, task backlog, recommendations."""
    return await usage_audit.get_audit()


# Cap concurrent transcript disk reads so the extension's mass-sync of ~100+
# sessions cannot stall the asyncio event loop (WebSockets /health go offline).
_transcript_read_sem: asyncio.Semaphore | None = None


def _get_transcript_read_sem() -> asyncio.Semaphore:
    global _transcript_read_sem
    if _transcript_read_sem is None:
        _transcript_read_sem = asyncio.Semaphore(3)
    return _transcript_read_sem


@app.get("/sessions/{name}/transcript")
async def get_transcript(name: str, auth: None = Depends(require_auth)) -> dict:
    """Return a session's conversation turns from its shared transcript JSONL.

    Lets the chat panel display turns done in the PTY terminal (the two share
    one transcript) — the single source of truth for the conversation.
    """
    name = _validate_session_name(name)
    async with _get_transcript_read_sem():
        turns = await asyncio.to_thread(session_store.read_transcript_turns, name)
    return {"turns": turns}


class HistorySyncTurn(BaseModel):
    role: str
    text: str


class HistorySyncRequest(BaseModel):
    turns: list[HistorySyncTurn] = Field(default_factory=list)


@app.post("/sessions/{name}/history/sync", status_code=204)
async def sync_session_history(
    name: str,
    body: HistorySyncRequest,
    auth: None = Depends(require_auth),
) -> None:
    """Backfill bridge transcript from the extension UI (Cursor sessions)."""
    name = _validate_session_name(name)
    if session_store.get_session(name) is None:
        raise HTTPException(status_code=404, detail="Session not found")
    session_store.sync_bridge_transcript(
        name, [t.model_dump() for t in body.turns],
    )


@app.post("/actions")
async def actions_endpoint(
    body: browser_relay.ActionRequest,
    auth: None = Depends(require_auth),
) -> dict:
    return await browser_relay.post_action(body, auth)


_OPENERS = {"darwin": ["open"], "linux": ["xdg-open"], "win32": ["cmd", "/c", "start", ""]}


@app.post("/open", status_code=204)
async def open_path(body: OpenPathRequest, auth: None = Depends(require_auth)) -> None:
    """Open a local file/folder with the OS default handler (loopback + auth only).

    Opens an existing path with `open`/`xdg-open`; never runs a shell command.
    """
    target = Path(body.path).expanduser()
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"Path not found: {target}")
    opener = _OPENERS.get(sys.platform)
    if not opener:
        raise HTTPException(status_code=400, detail=f"Unsupported platform: {sys.platform}")
    try:
        await asyncio.create_subprocess_exec(
            *opener, str(target),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except Exception as exc:  # noqa: BLE001 — surface any spawn failure to the UI
        raise HTTPException(status_code=500, detail=f"Failed to open: {exc}") from exc
    logger.info("Opened path: %s", target)


# ─────────────────────────────────────────────
# WebSocket endpoint
# ─────────────────────────────────────────────

async def _ws_auth(ws: WebSocket) -> bool:
    token = ws.query_params.get("token")
    if not token:
        auth_hdr = ws.headers.get("Authorization", "")
        token = auth_hdr[7:] if auth_hdr.startswith("Bearer ") else None
    if token != _startup_token:
        logger.warning("WS auth mismatch from %s", ws.client.host if ws.client else "unknown")
        return False
    return True


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


def _resolve_out_queue(session_name: str) -> asyncio.Queue:
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
    q = _resolve_out_queue(session_name)
    if pump_task is None or pump_task.done():
        pump_task = _start_session_pump(session_name, ws, q)
    return q, pump_task


async def _handle_session_command(
    ws: WebSocket, session_name: str, verb: str, prompt: str, pump_task: asyncio.Task | None,
) -> asyncio.Task | None:
    """Dispatch /medic, /interrupt, /ask — each on a separate path, never queued."""
    target = _parse_command_target(prompt, session_name)
    q, pump_task = _command_queue(session_name, ws, pump_task)

    if verb == "/medic":
        asyncio.ensure_future(watchdog_medic.run_medic(
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
            capability_router.run_on_queue("parallel_ask", question, session_name, q)
        )
    elif verb in ("/cursor-ctx", "/ctx"):
        parts = prompt.split(maxsplit=1)
        task = parts[1] if len(parts) > 1 else ""

        async def _run_cursor_ctx() -> None:
            nonlocal pump_task
            forward_q = await capability_router.run_on_queue(
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
            capability_router.run_on_queue("cursor_plugins", task, session_name, q)
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
        pump_task = _start_session_pump(session_name, ws, _resolve_out_queue(session_name))
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


@app.websocket("/pty/{terminal_id}")
async def pty_terminal(ws: WebSocket, terminal_id: str) -> None:
    """Real interactive terminal (PTY) — additive, separate from /ws sessions.

    Query params: cmd ("resume"|"claude"|"shell"), session (name, for --resume).
    """
    if not SESSION_NAME_RE.match(terminal_id):
        await ws.close(code=1008, reason="Invalid terminal id")
        return
    if not await _ws_auth(ws):
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


@app.websocket("/ws/{session_name}")
async def ws_session(ws: WebSocket, session_name: str) -> None:
    if not SESSION_NAME_RE.match(session_name):
        await ws.close(code=1008, reason="Invalid session name")
        return
    if not await _ws_auth(ws):
        await ws.close(code=4003, reason="Forbidden")
        return

    await ws.accept()
    browser_relay.register_ws(session_name, ws)
    # A1: pump attaches HERE, on connect — not lazily on first user_msg — so
    # frames already sitting in the session's persistent out_queue (e.g. from
    # before a reconnect) are delivered immediately, and a slash-command-first
    # WS still sees the real session's frames once it later spawns.
    q = _resolve_out_queue(session_name)
    pump_task = _start_session_pump(session_name, ws, q)
    logger.info("WS connected: session='%s'", session_name)
    try:
        await _ws_receive_loop(ws, session_name, pump_task)
    finally:
        browser_relay.deregister_ws(session_name, ws)


# ─────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────

def _assert_loopback_host(host: str) -> None:
    if host not in {"127.0.0.1", "::1", "localhost"}:
        raise RuntimeError(f"Dev Bridge must bind to loopback only. Refusing host={host!r}.")


_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
_LOG_MAX_BYTES = 50 * 1024 * 1024   # 50MB per file
_LOG_BACKUP_COUNT = 5               # ...x5 rotated files


def _configure_logging(log_dir: Path = BRIDGE_DIR) -> None:
    """A10/RC-12: timestamped, size-capped logs instead of an unbounded,
    timestamp-less stream. Bridge log files had grown to 312MB+3.2GB with no
    way to tell WHEN anything happened; uvicorn's access log also logged a
    line for every poll (GET /sessions, /transcript — hit every few seconds
    by a connected panel), drowning out anything worth reading.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(_LOG_FORMAT)

    file_handler = RotatingFileHandler(
        log_dir / "bridge.log", maxBytes=_LOG_MAX_BYTES, backupCount=_LOG_BACKUP_COUNT,
    )
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(stream_handler)

    # Poll-heavy endpoints would otherwise log an access line every few
    # seconds per connected panel — demote to WARNING (errors still surface).
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def run() -> None:
    """Console entry point: ``devscope-bridge``.

    Always a single uvicorn process. Multi-worker uvicorn would break in-memory
    PTY terminals, WebSocket session pumps, and the orchestrator loop.
    Concurrent HTTP is handled by asyncio; transcript reads are semaphore-capped.
    Orchestrator Claude workers are capped via ORCHESTRATOR_MAX_WORKERS / config.
    """
    host = os.environ.get("BRIDGE_HOST", "127.0.0.1")
    port = int(os.environ.get("BRIDGE_PORT", "7878"))
    _assert_loopback_host(host)
    _configure_logging()
    uvicorn.run(
        "devscope_bridge.main:app",
        host=host,
        port=port,
        log_level="info",
        reload=False,
        workers=1,
        # A10: uvicorn's own dictConfig would otherwise reset uvicorn.access
        # back to INFO with its own non-propagating handler, undoing the
        # _configure_logging() level/format above. log_config=None leaves our
        # root handlers as the only ones — uvicorn's loggers propagate to them.
        log_config=None,
        # log_level above re-applies INFO to uvicorn.access even with
        # log_config=None, so the polling noise (GET /sessions ~1Hz) must be
        # cut at the source; uvicorn.error still reports real problems.
        access_log=False,
    )


if __name__ == "__main__":
    run()
