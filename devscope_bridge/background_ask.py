"""
background_ask.py — Parallel side-queries (`/ask`).

Lets the user ask a question and get an answer WITHOUT interrupting or delaying
the currently running turn.  Unlike steering (a message queued to the main
session's stdin that runs AFTER the current turn), `/ask` spawns a SEPARATE
short-lived `claude --print` process — a fresh, single-turn conversation — and
streams its answer onto the SAME panel out_queue, interleaved with the main
turn.  The main session is never touched: its process, turn, and context are
unaffected.

Limits (per session): at most _MAX_CONCURRENT side-queries at once; each is
killed after _ASK_TIMEOUT_S.  Side-query context is ephemeral — never injected
into the main session.
"""

import asyncio
import json
import logging
import uuid

from devscope_bridge import session_manager
from devscope_bridge.models import AiChunk, AiError, AskChunk, AskDone, AskStart

logger = logging.getLogger(__name__)

_MAX_CONCURRENT = 3          # max simultaneous side-queries per session
_ASK_TIMEOUT_S = 60.0        # a side-query is a single short turn — kill if it overruns
_MAX_QUESTION_CHARS = 4000

# session name → number of in-flight side-queries
_active_asks: dict[str, int] = {}

_ASK_SYSTEM_PROMPT = (
    "You are a quick side-assistant inside the DevScope dev tool. Answer the "
    "question concisely and directly. You may Read/Grep the repo to answer, but "
    "do NOT edit files, run destructive commands, or use browser tools. End your "
    "turn when answered."
)


def _build_ask_args() -> list[str]:
    return [
        "claude", "--print",
        "--input-format", "stream-json",
        "--output-format", "stream-json",
        "--include-partial-messages", "--verbose",
        "--disallowed-tools", "AskUserQuestion",
        "--append-system-prompt", _ASK_SYSTEM_PROMPT,
    ]


def _encode_user_message(text: str) -> bytes:
    payload = {
        "type": "user",
        "message": {"role": "user", "content": [{"type": "text", "text": text}]},
    }
    return (json.dumps(payload) + "\n").encode("utf-8")


async def _spawn_ask_proc() -> asyncio.subprocess.Process:
    """Spawn the side-query process. Injectable for tests."""
    return await asyncio.create_subprocess_exec(
        *_build_ask_args(),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=session_manager.DEFAULT_CWD,
        env=session_manager.subscription_env(),
    )


async def _stream_ask_output(
    name: str, question_id: str, proc: asyncio.subprocess.Process, q: asyncio.Queue,
) -> None:
    assert proc.stdout is not None
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
                    await q.put(AskChunk(session=name, question_id=question_id, text=text))
        elif ev_type == "result":
            break


async def run_ask(name: str, q: asyncio.Queue, question: str) -> None:
    """Run a parallel side-query for session ``name``; stream the answer to ``q``.

    The main session keeps running.  Emits a dedicated AskStart/AskChunk/AskDone
    frame stream keyed by question_id so the panel renders it as a distinct
    parallel bubble.  Rejected (no bubble) if the question is empty or the
    per-session concurrency cap is reached.
    """
    question = question.strip()
    if not question:
        await q.put(AiChunk(session=name, text="\n\n_Usage: `/ask <your question>`_\n"))
        return
    if _active_asks.get(name, 0) >= _MAX_CONCURRENT:
        await q.put(AiError(
            session=name, exit_code=-1,
            stderr_tail=f"[bridge] Too many concurrent side-queries (max {_MAX_CONCURRENT}).",
        ))
        return
    if len(question) > _MAX_QUESTION_CHARS:
        question = question[:_MAX_QUESTION_CHARS] + " [truncated]"

    question_id = uuid.uuid4().hex
    _active_asks[name] = _active_asks.get(name, 0) + 1
    await q.put(AskStart(session=name, question_id=question_id, question=question))
    logger.info("Side-query for session '%s' (%s): %s", name, question_id[:8], question[:80])

    proc: asyncio.subprocess.Process | None = None
    ok = True
    try:
        proc = await _spawn_ask_proc()
        assert proc.stdin is not None
        proc.stdin.write(_encode_user_message(question))
        await proc.stdin.drain()
        proc.stdin.close()
        await asyncio.wait_for(_stream_ask_output(name, question_id, proc, q), timeout=_ASK_TIMEOUT_S)
    except asyncio.TimeoutError:
        ok = False
        await q.put(AskChunk(
            session=name, question_id=question_id,
            text=f"\n\n⚠️ Side-query timed out after {_ASK_TIMEOUT_S:.0f}s.",
        ))
    except Exception as exc:  # noqa: BLE001 — never let a side-query crash the bridge
        ok = False
        await q.put(AskChunk(session=name, question_id=question_id, text=f"\n\n⚠️ Side-query failed: {exc}"))
    finally:
        if proc is not None and proc.returncode is None:
            try:
                proc.terminate()
            except ProcessLookupError:
                pass
        _active_asks[name] = max(0, _active_asks.get(name, 1) - 1)
        await q.put(AskDone(session=name, question_id=question_id, ok=ok))
