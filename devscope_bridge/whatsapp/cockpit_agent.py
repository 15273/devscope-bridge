"""cockpit_agent.py — one-shot Claude or Cursor for WhatsApp cockpit Q&A."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from devscope_bridge import session_manager, session_store
from devscope_bridge import session_manager_cursor as cursor_mod
from devscope_bridge.models import AiChunk, AiDone, AiError
from devscope_bridge.mode_presets import MODE_PRESETS

logger = logging.getLogger(__name__)

_MCP_HINT = (
    "\n\nTOOLS: whatsapp-control MCP (wa_list_chats, wa_get_messages, wa_search) is "
    "available when using Cursor. If conversation history is empty or incomplete, "
    "fetch live messages before answering. Never claim you sent a message."
)


def _build_claude_args(system_prompt: str) -> list[str]:
    return [
        "claude", "--print",
        "--input-format", "stream-json",
        "--output-format", "stream-json",
        "--include-partial-messages", "--verbose",
        "--disallowed-tools", "AskUserQuestion",
        "--append-system-prompt", system_prompt,
    ]


def _encode_user_message(text: str) -> bytes:
    payload = {
        "type": "user",
        "message": {"role": "user", "content": [{"type": "text", "text": text}]},
    }
    return (json.dumps(payload) + "\n").encode("utf-8")


async def _collect_claude_output(proc: asyncio.subprocess.Process) -> str:
    assert proc.stdout is not None
    chunks: list[str] = []
    async for raw in proc.stdout:
        line = raw.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        ev_type = event.get("type")
        if ev_type == "stream_event":
            delta = event.get("event", {}).get("delta", {})
            if delta.get("type") == "text_delta":
                text = delta.get("text", "")
                if text:
                    chunks.append(text)
        elif ev_type == "result":
            break
    return "".join(chunks)


async def _run_claude(system_prompt: str, user_text: str, timeout_s: float) -> str:
    proc: asyncio.subprocess.Process | None = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *_build_claude_args(system_prompt),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=session_store.DEFAULT_CWD,
            env=session_manager.subscription_env(),
        )
        assert proc.stdin is not None
        proc.stdin.write(_encode_user_message(user_text))
        await proc.stdin.drain()
        proc.stdin.close()
        raw = await asyncio.wait_for(_collect_claude_output(proc), timeout=timeout_s)
        return raw.strip()
    except asyncio.TimeoutError:
        logger.warning("cockpit_agent claude: timed out after %.0fs", timeout_s)
        return ""
    except Exception as exc:  # noqa: BLE001
        logger.warning("cockpit_agent claude: failed: %s", exc)
        return ""
    finally:
        if proc is not None and proc.returncode is None:
            try:
                proc.terminate()
            except ProcessLookupError:
                pass


async def _run_cursor(
    system_prompt: str,
    user_text: str,
    *,
    session_name: str,
    model: str | None,
    mode: str | None,
    timeout_s: float,
) -> str:
    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue()
    full_prompt = system_prompt + "\n\n---\n\n" + user_text
    preset = MODE_PRESETS.get(mode or "act")
    if preset and preset.get("system_prompt_suffix"):
        full_prompt = preset["system_prompt_suffix"] + "\n\n" + full_prompt

    def blocking() -> None:
        cursor_mod._run_cursor_streaming_blocking(
            full_prompt,
            None,
            session_store.DEFAULT_CWD,
            mode,
            model,
            loop,
            q,
            session_name,
        )

    thread = asyncio.create_task(asyncio.to_thread(blocking))
    parts: list[str] = []
    try:
        async with asyncio.timeout(timeout_s):
            while True:
                frame = await q.get()
                if isinstance(frame, AiChunk):
                    parts.append(frame.text)
                elif isinstance(frame, AiError):
                    logger.warning("cockpit_agent cursor: %s", frame.stderr_tail[:200])
                    break
                elif isinstance(frame, AiDone):
                    break
    except TimeoutError:
        logger.warning("cockpit_agent cursor: timed out after %.0fs", timeout_s)
        cursor_mod.interrupt_cursor(session_name)
    await thread
    return "".join(parts).strip()


async def run(
    system_prompt: str,
    user_text: str,
    *,
    agent: str = "cursor",
    model: str | None = None,
    mode: str | None = "act",
    session_name: str | None = None,
    timeout_s: float = 120.0,
) -> str:
    """Run one scoped cockpit query. Returns '' on failure."""
    sys = system_prompt + (_MCP_HINT if agent == "cursor" else "")
    if agent == "cursor":
        name = session_name or "wa-cockpit"
        return await _run_cursor(
            sys, user_text, session_name=name, model=model, mode=mode, timeout_s=timeout_s,
        )
    return await _run_claude(sys, user_text, timeout_s)
