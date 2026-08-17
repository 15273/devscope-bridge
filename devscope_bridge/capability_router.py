"""
capability_router.py — invoke a registry capability over the EXISTING backends.

Two modes, same backend functions, zero duplicated logic:

- ``invoke()``      (devscope_invoke / POST /invoke): runs the backend with a
  PRIVATE collector queue, accumulates its AskChunk frames, and returns a
  synchronous ``{ok, summary, detail}`` dict to the caller (Claude).
- ``run_on_queue()`` (slash-command aliases): passes the SESSION queue straight
  through, so side bubbles render byte-identically to today.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any, Awaitable, Callable

from devscope_bridge import background_ask, background_cursor_context, background_cursor_task
from devscope_bridge import capability_registry
from devscope_bridge.models import AgentActivity

logger = logging.getLogger(__name__)

_SUMMARY_CHARS = 500
_FALLBACK_SESSION = "devscope-invoke"

# Outer collect timeouts — slightly above each backend's own internal timeout,
# so the backend's finally-block AskDone always wins over our backstop.
_BACKEND_TIMEOUT_S: dict[str, float] = {
    "cursor_agent": background_cursor_task._TIMEOUT_S + 30.0,
    "cursor_agent_ctx": background_cursor_context._TIMEOUT_S + 30.0,
    "claude_print": background_ask._ASK_TIMEOUT_S + 30.0,
}

BackendFn = Callable[..., Awaitable[Any]]


def _backend_fn(backend: str) -> tuple[BackendFn, dict[str, Any]] | None:
    if backend == "cursor_agent":
        return background_cursor_task.run_cursor_task, {}
    if backend == "cursor_agent_ctx":
        return background_cursor_context.run_cursor_context, {"forward": False}
    if backend == "claude_print":
        return background_ask.run_ask, {}
    return None


async def _drain(q: asyncio.Queue, deadline: float) -> tuple[bool, list[str], str | None]:
    """Consume frames until AskDone or a pre-start hint frame; return (ok, chunks, error)."""
    question_id: str | None = None
    chunks: list[str] = []
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise asyncio.TimeoutError
        frame = await asyncio.wait_for(q.get(), timeout=remaining)
        ftype = getattr(frame, "type", "")
        if ftype == "ask_start":
            question_id = frame.question_id
        elif ftype == "ask_chunk":
            if question_id is None:
                return False, [], frame.text.strip()  # usage/busy hint, no run started
            if frame.question_id == question_id:
                chunks.append(frame.text)
        elif ftype == "ai_chunk":
            return False, [], frame.text.strip()      # rejection hint (empty task, wrong agent)
        elif ftype == "ai_error":
            return False, [], frame.stderr_tail.strip()
        elif ftype == "ask_done":
            return bool(frame.ok), chunks, None
        # agent_activity and other frames are progress-only — skip.


async def _collect(fn: BackendFn, kwargs: dict[str, Any], name: str, task: str,
                   timeout_s: float, backend: str) -> dict[str, Any]:
    """Run one backend function against a private queue and capture its result."""
    q: asyncio.Queue = asyncio.Queue()
    started = time.monotonic()
    runner = asyncio.create_task(fn(name, q, task, **kwargs))
    try:
        ok, chunks, error = await _drain(q, started + timeout_s)
    except asyncio.TimeoutError:
        runner.cancel()
        return {"ok": False, "backend": backend,
                "error": f"Timed out after {timeout_s:.0f}s."}
    finally:
        if not runner.done():
            runner.cancel()
    elapsed_s = round(time.monotonic() - started, 1)
    if error is not None:
        return {"ok": False, "backend": backend, "error": error, "elapsed_s": elapsed_s}
    detail = "".join(chunks).strip()
    return {
        "ok": ok,
        "backend": backend,
        "summary": detail[:_SUMMARY_CHARS],
        "detail": detail,
        "elapsed_s": elapsed_s,
    }


async def _notify_session(session: str | None, capability: str, ok: bool) -> None:
    """Additive Pro-UI nicety: drop one activity row on the session's live queue."""
    if not session:
        return
    from devscope_bridge import main  # local import — main includes our routes

    q = main._resolve_out_queue(session)
    await q.put(AgentActivity(
        session=session,
        label=f"devscope_invoke: {capability}",
        tool="devscope_invoke",
        call_id=uuid.uuid4().hex,
        status="done" if ok else "error",
    ))


def _unavailable(cap: capability_registry.Capability, missing: list[str]) -> dict[str, Any]:
    return {
        "ok": False,
        "error": f"Capability '{cap.id}' is not available.",
        "missing": missing,
        "setup_hint": cap.setup_hint or None,
    }


async def invoke(capability: str, task: str, session: str | None = None,
                 wait: bool = True, timeout_s: float | None = None) -> dict[str, Any]:
    """Resolve a capability, run its first available backend, return a sync result."""
    cap = capability_registry.get_capability(capability)
    if cap is None:
        return {"ok": False,
                "error": f"Unknown capability '{capability}'.",
                "known": sorted(capability_registry.CAPABILITIES)}

    requires = await capability_registry.check_requires(cap)
    missing = [r for r, satisfied in requires.items() if not satisfied]
    if missing:
        return _unavailable(cap, missing)

    backend = cap.backends[0]
    if backend == "direct_mcp":
        return {"ok": False, "redirect": True,
                "summary": f"Use the {cap.label} MCP tools directly: {cap.mcp_hint}"}
    resolved = _backend_fn(backend)
    if resolved is None:
        return {"ok": False, "error": f"No adapter for backend '{backend}'."}

    fn, kwargs = resolved
    name = session or _FALLBACK_SESSION
    if cap.id.startswith("plugin:"):
        plugin = cap.id.split(":", 1)[1]
        task = f"Using the '{plugin}' plugin/MCP: {task}"
    if not wait:
        from devscope_bridge import main  # local import — main includes our routes

        asyncio.ensure_future(fn(name, main._resolve_out_queue(name), task, **kwargs))
        return {"ok": True, "started": True, "backend": backend,
                "note": "Running in the background; result streams to the session panel."}

    effective_timeout = timeout_s or _BACKEND_TIMEOUT_S.get(backend, 330.0)
    logger.info("capability invoke '%s' via %s (session=%s)", capability, backend, name)
    result = await _collect(fn, kwargs, name, task, effective_timeout, backend)
    await _notify_session(session, capability, bool(result.get("ok")))
    return result


async def run_on_queue(capability: str, task: str, session: str,
                       q: asyncio.Queue) -> asyncio.Queue | None:
    """Streaming alias path for slash commands — session queue, side bubbles as today.

    Skips availability gating on purpose: the slash path never gated beyond each
    backend's own preflight, and this must stay byte-identical.
    """
    cap = capability_registry.get_capability(capability)
    resolved = _backend_fn(cap.backends[0]) if cap else None
    if resolved is None:
        logger.warning("run_on_queue: no backend for capability '%s'", capability)
        return None
    fn, kwargs = resolved
    if fn is background_cursor_context.run_cursor_context:
        return await background_cursor_context.run_cursor_context(session, q, task)
    await fn(session, q, task, **kwargs)
    return None
