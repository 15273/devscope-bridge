"""Core HTTP routes: sessions, commands, quota, transcript, browser actions."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from devscope_bridge import browser_relay
from devscope_bridge import compact_service
from devscope_bridge import oauth_usage_service
from devscope_bridge import quota_service
from devscope_bridge import session_manager
from devscope_bridge import session_reader
from devscope_bridge import session_store
from devscope_bridge import usage_audit
from devscope_bridge import builtin_commands as _builtins
from devscope_bridge.agents_scanner import scan_agents
from devscope_bridge.bridge_auth import require_auth, validate_session_name, SESSION_NAME_RE
from devscope_bridge.commands_scanner import scan_commands
from devscope_bridge.models import (
    OpenPathRequest, SessionCreateRequest, SessionInfo, SessionsResponse,
)
from devscope_bridge.ws_session import resolve_out_queue

logger = logging.getLogger(__name__)

router = APIRouter()

_VALID_AGENTS = {"claude", "cursor"}


@router.get("/capabilities")
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


@router.get("/sessions", response_model=SessionsResponse)
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


@router.post("/sessions", status_code=201)
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


@router.delete("/sessions/{name}", status_code=204)
async def delete_session(name: str, auth: None = Depends(require_auth)) -> None:
    name = validate_session_name(name)
    await session_manager.kill_session(name)
    session_store.delete_session(name)
    # A1: only forget the persistent out_queue on a FULL delete — kill_session
    # alone (reset/respawn/PTY handoff) must keep it so an already-attached WS
    # pump stays valid.
    session_manager.forget_out_queue(name)


@router.post("/sessions/{name}/interrupt", status_code=204)
async def interrupt_session_endpoint(name: str, auth: None = Depends(require_auth)) -> None:
    name = validate_session_name(name)
    if not session_manager.interrupt_session(name):
        raise HTTPException(status_code=404, detail="No active subprocess for this session")


@router.post("/sessions/{name}/reset", status_code=204)
async def reset_session_endpoint(name: str, auth: None = Depends(require_auth)) -> None:
    """Kill a hung subprocess without deleting session metadata.

    Claude: clear session_id when resume would replay a broken turn.
    Cursor: keep chatId so --resume continues the thread.
    """
    name = validate_session_name(name)
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


@router.post("/sessions/{name}/model")
async def set_session_model_endpoint(
    name: str,
    body: SessionModelRequest,
    auth: None = Depends(require_auth),
) -> dict:
    """Set or clear the Claude model for a session (no chat turn)."""
    name = validate_session_name(name)
    if session_store.get_session(name) is None:
        raise HTTPException(status_code=404, detail="Session not found")
    model = body.model.strip() if body.model else None
    applied = _builtins.apply_session_model(name, model)
    return {"ok": True, "model": applied}


@router.post("/sessions/{name}/claude-agent")
async def set_session_claude_agent_endpoint(
    name: str,
    body: SessionClaudeAgentRequest,
    auth: None = Depends(require_auth),
) -> dict:
    """Set or clear the Claude subagent (--agent) for a session (no chat turn)."""
    name = validate_session_name(name)
    if session_store.get_session(name) is None:
        raise HTTPException(status_code=404, detail="Session not found")
    slug = body.claude_agent.strip() if body.claude_agent else None
    if slug:
        known = {a["name"] for a in scan_agents()}
        if known and slug not in known:
            raise HTTPException(status_code=422, detail=f"Unknown claude agent: {slug}")
    applied = _builtins.apply_session_claude_agent(name, slug)
    return {"ok": True, "claude_agent": applied}


@router.post("/sessions/{name}/compact")
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
    name = validate_session_name(name)
    q = resolve_out_queue(name)
    result = await compact_service.guarded_compact(name, body.extra, q)
    if not result.ok:
        return {"ok": False, "error": result.skipped}
    await compact_service.apply_compact_reset(name, result.preamble, result.was_real_summary)
    return {"ok": True, "was_real_summary": result.was_real_summary}


@router.get("/sessions/{name}/pending")
async def get_pending_endpoint(name: str, auth: None = Depends(require_auth)) -> dict:
    """Unresolved interactive requests for a session (contract 3 / A2).

    Lets a panel that was closed, reloaded, or disconnected while a
    PermissionRequest (plan / ask_user / tool_blocked) was pending recover
    the card on reopen instead of losing it silently.
    """
    name = validate_session_name(name)
    return {"pending": session_reader.get_pending_permissions(name)}


@router.get("/commands")
async def list_commands(auth: None = Depends(require_auth)) -> dict:
    """List available slash commands from project + user .claude dirs."""
    return {"commands": scan_commands()}


@router.get("/claude-agents")
async def list_claude_agents(auth: None = Depends(require_auth)) -> dict:
    """List Claude Code subagents from .claude/agents/*.md."""
    return {"agents": scan_agents()}


@router.get("/quota")
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


@router.get("/usage/audit")
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


@router.get("/sessions/{name}/transcript")
async def get_transcript(name: str, auth: None = Depends(require_auth)) -> dict:
    """Return a session's conversation turns from its shared transcript JSONL.

    Lets the chat panel display turns done in the PTY terminal (the two share
    one transcript) — the single source of truth for the conversation.
    """
    name = validate_session_name(name)
    async with _get_transcript_read_sem():
        turns = await asyncio.to_thread(session_store.read_transcript_turns, name)
    return {"turns": turns}


class HistorySyncTurn(BaseModel):
    role: str
    text: str


class HistorySyncRequest(BaseModel):
    turns: list[HistorySyncTurn] = Field(default_factory=list)


@router.post("/sessions/{name}/history/sync", status_code=204)
async def sync_session_history(
    name: str,
    body: HistorySyncRequest,
    auth: None = Depends(require_auth),
) -> None:
    """Backfill bridge transcript from the extension UI (Cursor sessions)."""
    name = validate_session_name(name)
    if session_store.get_session(name) is None:
        raise HTTPException(status_code=404, detail="Session not found")
    session_store.sync_bridge_transcript(
        name, [t.model_dump() for t in body.turns],
    )


@router.post("/actions")
async def actions_endpoint(
    body: browser_relay.ActionRequest,
    auth: None = Depends(require_auth),
) -> dict:
    return await browser_relay.post_action(body, auth)


_OPENERS = {"darwin": ["open"], "linux": ["xdg-open"], "win32": ["cmd", "/c", "start", ""]}


@router.post("/open", status_code=204)
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

