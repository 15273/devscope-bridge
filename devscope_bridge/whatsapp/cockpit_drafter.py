"""cockpit_drafter.py — Suggest 1-3 reply phrasings from recent thread context.

Uses a one-shot ``claude --print`` subprocess (same pattern as compact_service.py).
Never sends — returns candidate strings only; the caller must get explicit user
confirmation before sending.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from devscope_bridge import session_manager, session_store

logger = logging.getLogger(__name__)

_TIMEOUT_S = 30.0

_SYSTEM_PROMPT = (
    "You are helping the user reply on WhatsApp. "
    "Given the recent conversation, suggest 3 short reply options in the SAME "
    "language as the conversation (detect automatically — Hebrew, English, etc.), "
    "varied in tone (warm / brief / detailed). "
    'Return ONLY valid JSON: {"candidates": ["...", "...", "..."]}. '
    "No explanation, no markdown fences — raw JSON only."
)


def _build_args() -> list[str]:
    return [
        "claude", "--print",
        "--input-format", "stream-json",
        "--output-format", "stream-json",
        "--include-partial-messages", "--verbose",
        "--disallowed-tools", "AskUserQuestion",
        "--append-system-prompt", _SYSTEM_PROMPT,
    ]


def _encode_user_message(text: str) -> bytes:
    payload = {
        "type": "user",
        "message": {"role": "user", "content": [{"type": "text", "text": text}]},
    }
    return (json.dumps(payload) + "\n").encode("utf-8")


async def _spawn_proc() -> asyncio.subprocess.Process:
    return await asyncio.create_subprocess_exec(
        *_build_args(),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=session_store.DEFAULT_CWD,
        env=session_manager.subscription_env(),
    )


async def _collect_output(proc: asyncio.subprocess.Process) -> str:
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


def _build_thread_prompt(messages: list[dict[str, Any]]) -> str:
    lines = [
        f"{'me' if m.get('from_me') else 'them'}: {m.get('text', '')}"
        for m in messages if m.get("text")
    ]
    thread = "\n".join(lines)
    return f"Conversation:\n{thread}"


async def suggest(messages: list[dict[str, Any]]) -> list[str]:
    """Return 1-3 candidate reply strings based on recent messages.

    Messages should be in chronological order (oldest first). Returns [] on
    timeout or subprocess failure — never raises.
    """
    if not messages:
        return []

    prompt = _build_thread_prompt(messages)
    proc: asyncio.subprocess.Process | None = None
    try:
        proc = await _spawn_proc()
        assert proc.stdin is not None
        proc.stdin.write(_encode_user_message(prompt))
        await proc.stdin.drain()
        proc.stdin.close()

        raw = await asyncio.wait_for(_collect_output(proc), timeout=_TIMEOUT_S)
        raw = raw.strip()
        if not raw:
            return []
        try:
            data = json.loads(raw)
            candidates = [c for c in data.get("candidates", []) if isinstance(c, str)]
            return candidates[:3] if candidates else [raw]
        except (ValueError, TypeError):
            return [raw]
    except asyncio.TimeoutError:
        logger.warning("cockpit_drafter: suggest timed out after %.0fs", _TIMEOUT_S)
        return []
    except Exception as exc:  # noqa: BLE001
        logger.warning("cockpit_drafter: suggest failed: %s", exc)
        return []
    finally:
        if proc is not None and proc.returncode is None:
            try:
                proc.terminate()
            except ProcessLookupError:
                pass
