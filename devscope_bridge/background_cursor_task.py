"""
background_cursor_task.py — Parallel Cursor agent with full MCP (`/cursor-task`).

Runs cursor-agent in act mode with --approve-mcps so workspace MCP servers
(.cursor/mcp.json) and Cursor-account plugins (e.g. Notion) are available.
Result streams into a dashed side bubble — the main Claude/Cursor turn is untouched.
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import uuid

from devscope_bridge import session_manager
from devscope_bridge.cursor_workspace import find_devscope_workspace
from devscope_bridge.models import AgentActivity, AskChunk, AskDone, AskStart
from devscope_bridge.session_manager_cursor import (
    _build_cursor_args,
    _cursor_agent_env,
    _cursor_activities_from_obj,
    _parse_line_to_delta,
    _resolve_cursor_bin,
    _spawn_stderr_drain,
)

logger = logging.getLogger(__name__)

_MAX_CONCURRENT = 1
_TIMEOUT_S = 300.0
_MAX_TASK_CHARS = 8000

_active: dict[str, int] = {}

_NOTION_HINTS = ("notion", "נושיין", "נושן")

_TASK_PREFIX = (
    "You are running inside DevScope with Cursor MCP tools enabled.\n"
    "Rules:\n"
    "- Use only MCP servers relevant to the task. Do NOT call whatsapp-control, "
    "browser_wa_store, gmail-control, or calendar-control unless the task explicitly "
    "mentions WhatsApp, Gmail, or Calendar.\n"
    "- For Notion: use the Notion MCP/plugin only if it is in your tool list. "
    "If Notion is unavailable, say so clearly — do not substitute other tools.\n"
    "- Answer in the same language as the task.\n\n"
    "Task:\n"
)


def _task_mentions_notion(task: str) -> bool:
    lower = task.lower()
    return any(h in lower for h in _NOTION_HINTS)


def _mcp_list_status() -> dict[str, str]:
    """Return server→status from `cursor-agent mcp list` (empty on failure)."""
    binary = _resolve_cursor_bin()
    if not binary:
        return {}
    try:
        out = subprocess.run(
            [binary, "mcp", "list"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    status: dict[str, str] = {}
    for line in (out.stdout or "").splitlines():
        if ":" not in line:
            continue
        name, _, rest = line.partition(":")
        status[name.strip()] = rest.strip()
    return status


def _notion_mcp_ready(status: dict[str, str]) -> bool:
    for name, state in status.items():
        if "notion" in name.lower() and state.lower().startswith("ready"):
            return True
    return False


async def run_cursor_task(name: str, q: asyncio.Queue, task: str) -> None:
    task = task.strip()
    if not task:
        await q.put(AskChunk(
            session=name,
            question_id="usage",
            text="\n\n_Usage: `/cursor-task <what Cursor should do with MCP plugins>`_"
            "\n_Example: `/cursor-task List my open Notion tasks and summarize blockers`_",
        ))
        return
    if _active.get(name, 0) >= _MAX_CONCURRENT:
        await q.put(AskChunk(
            session=name,
            question_id="busy",
            text="\n\n⚠️ A Cursor MCP task is already running on this session.",
        ))
        return
    if len(task) > _MAX_TASK_CHARS:
        task = task[:_MAX_TASK_CHARS] + " [truncated]"

    question_id = uuid.uuid4().hex
    _active[name] = _active.get(name, 0) + 1
    await q.put(AskStart(session=name, question_id=question_id, question=task, kind="cursor_task"))
    logger.info("Cursor MCP task for '%s' (%s): %s", name, question_id[:8], task[:80])

    if _task_mentions_notion(task):
        raw = await asyncio.to_thread(_mcp_list_status)
        mcp_status = raw if isinstance(raw, dict) else {}
        if not _notion_mcp_ready(mcp_status):
            await q.put(AskChunk(
                session=name,
                question_id=question_id,
                text=(
                    "\n\n⚠️ **Notion is not connected** on this machine "
                    "(not in `cursor-agent mcp list`).\n"
                    "Connect it in **Cursor IDE → Settings → MCP / Plugins → Notion**, "
                    "then run `cursor-agent mcp list` until a Notion line shows `ready`.\n"
                    "DevScope `.cursor/mcp.json` does not include Notion — it uses your "
                    "Cursor account plugins.\n\n"
                ),
            ))

    ok = True
    loop = asyncio.get_running_loop()
    try:
        await asyncio.wait_for(
            asyncio.to_thread(_run_blocking, name, question_id, task, q, loop),
            timeout=_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        ok = False
        await q.put(AskChunk(
            session=name,
            question_id=question_id,
            text=f"\n\n⚠️ Cursor MCP task timed out after {_TIMEOUT_S:.0f}s.",
        ))
    except FileNotFoundError as exc:
        ok = False
        await q.put(AskChunk(session=name, question_id=question_id, text=f"\n\n⚠️ {exc}"))
    except Exception as exc:  # noqa: BLE001
        ok = False
        await q.put(AskChunk(session=name, question_id=question_id, text=f"\n\n⚠️ Cursor task failed: {exc}"))
    finally:
        _active[name] = max(0, _active.get(name, 1) - 1)
        await q.put(AskDone(session=name, question_id=question_id, ok=ok))


def _run_blocking(
    name: str,
    question_id: str,
    task: str,
    q: asyncio.Queue,
    loop: asyncio.AbstractEventLoop,
) -> None:
    def _put(frame) -> None:
        asyncio.run_coroutine_threadsafe(q.put(frame), loop).result(timeout=30)

    binary = _resolve_cursor_bin()
    if not binary:
        raise FileNotFoundError(
            "cursor-agent not found. Install: curl https://cursor.com/install -fsS | bash"
        )

    cwd = session_manager._session_cwd(name)  # noqa: SLF001
    workspace = find_devscope_workspace(cwd)
    prompt = _TASK_PREFIX + task
    cmd = _build_cursor_args(binary, prompt, None, "act", None, workspace=workspace)

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=cwd,
        env=_cursor_agent_env(name, cwd),
    )
    # B2 — drain stderr concurrently so a verbose child never deadlocks on a
    # full pipe buffer while we're still reading stdout live.
    stderr_buf = _spawn_stderr_drain(proc)

    accum = ""
    emitted_any = False
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                obj = json.loads(stripped)
                for label, tool, detail, status in _cursor_activities_from_obj(obj):
                    _put(AgentActivity(session=name, label=label, tool=tool, detail=detail, status=status))
            except json.JSONDecodeError:
                pass

            delta, accum, _ = _parse_line_to_delta(line, accum)
            if delta:
                emitted_any = True
                _put(AskChunk(session=name, question_id=question_id, text=delta))
    finally:
        proc.wait(timeout=30)

    # cursor-agent failures (e.g. "Authentication required") go to stderr and exit
    # fast — without this they surface as a silent ok=True with empty output.
    if not emitted_any:
        stderr_tail = "".join(stderr_buf).strip()[-400:]
        if proc.returncode != 0 or stderr_tail:
            raise RuntimeError(
                f"cursor-agent exited {proc.returncode} with no output"
                + (f": {stderr_tail}" if stderr_tail else "")
            )
