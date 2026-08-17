"""
background_english_coach.py — Parallel English-coach side-query.

After each user message the bridge fires a short-lived ``claude --print`` process
that analyses the user's text and returns a mini English lesson in their native
language (default Hebrew).  The lesson streams to the panel via
AskStart(kind="english_coach") / AskChunk* / AskDone frames, keyed by a fresh
question_id — the same wire format used by ``background_ask.py``.

The coding turn is completely unaffected: this is a fire-and-forget side-query
that never touches the main session.
"""

import asyncio
import json
import logging
import time
import uuid

from devscope_bridge import session_store
from devscope_bridge import session_manager
from devscope_bridge.models import AskChunk, AskDone, AskStart

logger = logging.getLogger(__name__)

_MAX_CONCURRENT = 1          # one coach card per session at a time
_TIMEOUT_S = 45.0            # single-turn lesson — kill if it overruns
_MAX_TEXT_CHARS = 3000       # truncate runaway user messages

# session name → number of in-flight coaches
_active_coaches: dict[str, int] = {}

# session → asyncio.Lock — dedupe concurrent coach starts for the same session
_coach_start_locks: dict[str, asyncio.Lock] = {}

# session → (normalized text, monotonic timestamp) — skip duplicate coach within window
_last_coach_prompt: dict[str, tuple[str, float]] = {}
_COACH_DEDUPE_S = 30.0


_FOCUS_LABELS: dict[str, str] = {
    "vocabulary": "vocabulary & word choice (synonyms, richer expressions, word variety)",
    "grammar": "grammar (tense, articles, prepositions, subject-verb agreement)",
    "spelling": "spelling & typos (correct spelling, capitalization, common misspellings)",
    "sentences": "sentence structure (flow, clarity, punctuation, run-ons, fragments)",
}

_ALL_FOCUS = list(_FOCUS_LABELS.keys())


def _build_coach_system_prompt(native_lang: str, coach_focus: list[str]) -> str:
    """Build the system prompt, parameterised by language and focus areas."""
    active = [k for k in coach_focus if k in _FOCUS_LABELS] or _ALL_FOCUS
    is_full = set(active) == set(_ALL_FOCUS)

    if is_full:
        focus_instruction = (
            "Use these sections (include only sections that are relevant):\n"
            "✅ What's correct — praise correct usage briefly.\n"
            "✏️ Corrections — list each error as: original → corrected.\n"
            "📐 Grammar rule — ONE relevant rule, explained simply.\n"
            "💬 More natural phrasing — a more native-sounding alternative for the whole message.\n"
            "📖 Word/phrase to learn — 1–2 English words or expressions from this message."
        )
    else:
        labels = " | ".join(_FOCUS_LABELS[k] for k in active)
        focus_instruction = (
            f"Focus ONLY on: {labels}. "
            f"Do NOT comment on other aspects of the writing. "
            f"Use only the relevant sections from:\n"
            f"✅ What's correct (in the focused areas)\n"
            f"✏️ Corrections — original → corrected (focused areas only)\n"
            f"📐 Rule — one rule from the focused area\n"
            f"📖 Word/phrase to learn (only if vocabulary is in focus)"
        )

    return (
        f"You are a passive English coach embedded inside a developer tool. "
        f"The user's native language is '{native_lang}'. "
        f"After each message the user sends to the coding assistant, analyse it for "
        f"English and return a SHORT, friendly mini-lesson "
        f"WRITTEN IN '{native_lang}' (not English). "
        f"{focus_instruction}\n\n"
        f"If the user wrote in '{native_lang}' (not English), show the correct English "
        f"version of their message and explain key vocabulary.\n\n"
        f"Keep the lesson proportional: few/no errors → very short (1–3 lines). "
        f"Many errors → more thorough. Do NOT comment on code blocks, commands, or "
        f"technical jargon — only natural language prose."
    )


def _build_coach_args(native_lang: str, coach_focus: list[str]) -> list[str]:
    return [
        "claude", "--print",
        "--input-format", "stream-json",
        "--output-format", "stream-json",
        "--include-partial-messages", "--verbose",
        "--disallowed-tools", "AskUserQuestion",
        "--append-system-prompt", _build_coach_system_prompt(native_lang, coach_focus),
    ]


def _encode_user_message(text: str) -> bytes:
    payload = {
        "type": "user",
        "message": {"role": "user", "content": [{"type": "text", "text": text}]},
    }
    return (json.dumps(payload) + "\n").encode("utf-8")


def _get_last_assistant_text(session_name: str) -> str | None:
    """Best-effort: return the most recent assistant turn from the transcript.

    Used as optional "phrasing to imitate" context. Returns None on any failure
    so the caller can silently skip it.
    """
    try:
        turns = session_store.read_transcript_turns(session_name)
        for turn in reversed(turns):
            if turn.get("role") == "assistant":
                text = turn.get("text", "").strip()
                if text:
                    return text[:800]   # keep the context snippet short
    except Exception:  # noqa: BLE001
        pass
    return None


def _build_coach_input(user_text: str, prior_assistant: str | None) -> str:
    """Compose the full message to send to the coach subprocess."""
    parts = [f"User message to analyse:\n{user_text}"]
    if prior_assistant:
        parts.append(
            f"\n---\nFor reference, here is the AI assistant's previous reply "
            f"(a good model of natural English phrasing):\n{prior_assistant}"
        )
    return "\n".join(parts)


async def _spawn_coach_proc(native_lang: str, coach_focus: list[str]) -> asyncio.subprocess.Process:
    """Spawn the coach subprocess. Injectable for tests."""
    return await asyncio.create_subprocess_exec(
        *_build_coach_args(native_lang, coach_focus),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=session_manager.DEFAULT_CWD,
        env=session_manager.subscription_env(),
    )


async def _stream_coach_output(
    session_name: str,
    question_id: str,
    proc: asyncio.subprocess.Process,
    q: asyncio.Queue,
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
                    await q.put(AskChunk(
                        session=session_name, question_id=question_id, text=text,
                    ))
        elif ev_type == "result":
            break


async def run_english_coach(
    session_name: str,
    q: asyncio.Queue,
    user_text: str,
    native_lang: str = "he",
    coach_focus: list[str] | None = None,
) -> None:
    """Run a parallel English-coach turn for session ``session_name``.

    Streams the lesson to ``q`` via AskStart/AskChunk/AskDone frames keyed by a
    fresh question_id.  Silently skipped if the concurrency cap is reached.
    Never raises — any failure emits AskDone(ok=False) and returns.

    Args:
        session_name: Bridge session identifier.
        q: The session's out_queue (shared with the main turn pump).
        user_text: The raw user message that was sent to the coding agent.
        native_lang: BCP-47 language code for the lesson language (default "he").
        coach_focus: Which areas to focus on (vocabulary/grammar/spelling/sentences).
                     None or empty list means all areas.
    """
    if coach_focus is None:
        coach_focus = []
    user_text = user_text.strip()
    if not user_text:
        return

    lock = _coach_start_locks.setdefault(session_name, asyncio.Lock())
    async with lock:
        norm = user_text.lower()
        now = time.monotonic()
        prev = _last_coach_prompt.get(session_name)
        if prev and prev[0] == norm and now - prev[1] < _COACH_DEDUPE_S:
            logger.debug(
                "English coach for '%s' skipped: duplicate prompt within %.0fs",
                session_name, _COACH_DEDUPE_S,
            )
            return
        _last_coach_prompt[session_name] = (norm, now)

        if _active_coaches.get(session_name, 0) >= _MAX_CONCURRENT:
            logger.debug(
                "English coach for '%s' skipped: concurrency cap (%d) reached",
                session_name, _MAX_CONCURRENT,
            )
            return

        if len(user_text) > _MAX_TEXT_CHARS:
            user_text = user_text[:_MAX_TEXT_CHARS] + " [truncated]"

        question_id = uuid.uuid4().hex
        _active_coaches[session_name] = _active_coaches.get(session_name, 0) + 1
        await q.put(AskStart(
            session=session_name,
            question_id=question_id,
            question=user_text,
            kind="english_coach",
        ))
        logger.info(
            "English coach for session '%s' (%s) lang=%s focus=%s: %.80s",
            session_name, question_id[:8], native_lang, coach_focus or "all", user_text,
        )

        proc: asyncio.subprocess.Process | None = None
        ok = True
        try:
            prior_assistant = _get_last_assistant_text(session_name)
            coach_input = _build_coach_input(user_text, prior_assistant)

            proc = await _spawn_coach_proc(native_lang, coach_focus)
            assert proc.stdin is not None
            proc.stdin.write(_encode_user_message(coach_input))
            await proc.stdin.drain()
            proc.stdin.close()

            await asyncio.wait_for(
                _stream_coach_output(session_name, question_id, proc, q),
                timeout=_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            ok = False
            await q.put(AskChunk(
                session=session_name,
                question_id=question_id,
                text=f"\n\n⚠️ English coach timed out after {_TIMEOUT_S:.0f}s.",
            ))
        except Exception as exc:  # noqa: BLE001 — never let a coach failure crash the bridge
            ok = False
            await q.put(AskChunk(
                session=session_name,
                question_id=question_id,
                text=f"\n\n⚠️ English coach failed: {exc}",
            ))
        finally:
            if proc is not None and proc.returncode is None:
                try:
                    proc.terminate()
                except ProcessLookupError:
                    pass
            _active_coaches[session_name] = max(0, _active_coaches.get(session_name, 1) - 1)
            await q.put(AskDone(session=session_name, question_id=question_id, ok=ok))
