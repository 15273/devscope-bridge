"""
background_cursor_context.py — Cursor codebase scout → Claude task (`/cursor-ctx`).

Flow:
  1. User on a **Claude** DevScope session runs `/cursor-ctx <task>`.
  2. A separate cursor-agent subprocess (inspect / ask mode) explores the repo
     read-only and returns structured context (paths, symbols, data flow).
  3. The scout streams into a dashed side bubble (like `/ask`).
  4. On success, the bridge forwards a combined prompt to the main Claude session.

Parallel to the main turn (like `/ask`) unless the forward step starts a new
Claude turn after the scout finishes.
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from devscope_bridge import session_manager, session_store
from devscope_bridge.models import AgentActivity, AiChunk, AskChunk, AskDone, AskStart
from devscope_bridge.session_manager_cursor import (
    _parse_chunk_from_event,
    _run_cursor_streaming,
)

logger = logging.getLogger(__name__)

_MAX_CONCURRENT = 2
_TIMEOUT_S = 180.0
_MAX_TASK_CHARS = 4000

_active_scouts: dict[str, int] = {}

_SCOUT_PROMPT_PREFIX = (
    "You are a codebase context scout for DevScope.\n"
    "Explore the repository using read-only tools (Read, Grep, Glob, search).\n"
    "Return structured markdown ONLY — no code edits, no shell, no fixes.\n\n"
    "Required sections:\n"
    "## Summary\n"
    "## Key files (absolute or repo-relative paths)\n"
    "## Relevant symbols (functions, classes, components)\n"
    "## Data / call flow\n"
    "## Gaps / open questions\n\n"
    "Task to gather context for:\n"
)


def _session_agent(name: str) -> str:
    stored = session_store.get_session(name)
    return (stored or {}).get("agent", "claude")


def _session_cwd(name: str) -> str:
    return session_manager._session_cwd(name)  # noqa: SLF001 — shared cwd helper


def _build_claude_task(task: str, context_md: str) -> str:
    return (
        "## Codebase context (Cursor scout — read-only)\n\n"
        f"{context_md.strip()}\n\n"
        "---\n\n"
        "## Your task\n\n"
        f"{task.strip()}\n\n"
        "Use the scout context above. Only re-read the repo if something critical "
        "is missing — do not repeat the full exploration."
    )


async def run_cursor_context(
    name: str,
    q: asyncio.Queue,
    task: str,
    forward: bool = True,
) -> asyncio.Queue | None:
    """Run Cursor scout; on success forward combined prompt to Claude.

    Returns the Claude out_queue if a forward turn was started (may differ from
    ``q`` when the session was idle before the forward).  With ``forward=False``
    (capability_router path — the caller IS Claude) the scout output is only
    streamed to ``q`` and no forward turn starts.
    """
    task = task.strip()
    if not task:
        await q.put(AiChunk(
            session=name,
            text="\n\n_Usage: `/cursor-ctx <what you want Claude to do>`_\n"
            "_Example: `/cursor-ctx Fix pagination on the jobs-app page — map the relevant files first`_",
        ))
        return None

    if forward and _session_agent(name) != "claude":
        await q.put(AiChunk(
            session=name,
            text="\n\n_`/cursor-ctx` works on **Claude** sessions only — Cursor scouts the code, "
            "Claude executes the task._\n",
        ))
        return None

    if _active_scouts.get(name, 0) >= _MAX_CONCURRENT:
        await q.put(AiChunk(
            session=name,
            text=f"\n\n_[bridge] Too many concurrent Cursor scouts (max {_MAX_CONCURRENT})._\n",
        ))
        return None

    if len(task) > _MAX_TASK_CHARS:
        task = task[:_MAX_TASK_CHARS] + " [truncated]"

    question_id = uuid.uuid4().hex
    _active_scouts[name] = _active_scouts.get(name, 0) + 1
    await q.put(AskStart(
        session=name,
        question_id=question_id,
        question=task,
        kind="cursor_ctx",
    ))
    logger.info("Cursor scout for session '%s' (%s): %s", name, question_id[:8], task[:80])

    cwd = _session_cwd(name)
    scout_prompt = _SCOUT_PROMPT_PREFIX + task
    ok = False
    collected: list[str] = []

    try:
        returncode, lines, stderr_tail = await asyncio.wait_for(
            asyncio.to_thread(
                _run_cursor_streaming,
                scout_prompt,
                None,
                cwd,
                "inspect",
                None,
            ),
            timeout=_TIMEOUT_S,
        )
        for line in lines:
            piece = _parse_chunk_from_event(line)
            if piece:
                collected.append(piece)
                await q.put(AskChunk(session=name, question_id=question_id, text=piece))

        if not collected:
            raw = "\n".join(l.strip() for l in lines if l.strip())
            if raw:
                collected.append(raw)
                await q.put(AskChunk(session=name, question_id=question_id, text=raw))

        ok = returncode == 0 and bool("".join(collected).strip())
        if not ok and stderr_tail:
            await q.put(AskChunk(
                session=name,
                question_id=question_id,
                text=f"\n\n⚠️ Cursor scout failed (exit {returncode}): {stderr_tail[:400]}",
            ))
    except asyncio.TimeoutError:
        await q.put(AskChunk(
            session=name,
            question_id=question_id,
            text=f"\n\n⚠️ Cursor scout timed out after {_TIMEOUT_S:.0f}s.",
        ))
    except FileNotFoundError as exc:
        await q.put(AskChunk(session=name, question_id=question_id, text=f"\n\n⚠️ {exc}"))
    except Exception as exc:  # noqa: BLE001
        await q.put(AskChunk(session=name, question_id=question_id, text=f"\n\n⚠️ Scout failed: {exc}"))
    finally:
        _active_scouts[name] = max(0, _active_scouts.get(name, 1) - 1)
        await q.put(AskDone(session=name, question_id=question_id, ok=ok))

    if not ok or not forward:
        return None

    context_md = "".join(collected).strip()
    combined = _build_claude_task(task, context_md)
    await q.put(AgentActivity(
        session=name,
        label="Claude",
        detail="Running your task with Cursor codebase context…",
    ))
    session_manager.reset_idle(name)
    forward_q = await session_manager.run_prompt(name, combined, mode="act")
    return forward_q
