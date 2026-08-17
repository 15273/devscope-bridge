"""
compact_service.py — Real conversation summarization for /compact.

Produces an honest summary of the FULL transcript by sending all turns to a
one-shot `claude --print` process (same pattern as background_ask / watchdog_medic).
Falls back to build_recovery_preamble when the transcript is empty or the
subprocess call fails/times out.

Public API
----------
do_compact(name, extra_instructions) -> (preamble: str, was_real_summary: bool)
    Reads the session's transcript, calls the summarizer, returns the preamble
    and a flag indicating whether a real summary was produced.
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from devscope_bridge import session_manager, session_reader, session_store
from devscope_bridge.models import AgentActivity

logger = logging.getLogger(__name__)

# Cap the transcript text sent to the summarizer so huge sessions don't blow up.
_TRANSCRIPT_CHAR_CAP = 40_000
_SUMMARIZE_TIMEOUT_S = 120.0
# Retry the one-shot summarizer once before falling back — the first spawn often
# fails transiently on a loaded machine, and a thin fallback loses real context.
_SUMMARIZE_MAX_ATTEMPTS = 2
# When the summarizer is unavailable, keep this much raw transcript tail so the
# fresh CLI context still has the recent conversation (far richer than 3+2 turns).
_FALLBACK_TRANSCRIPT_TAIL_CHARS = 12_000

_SUMMARIZE_SYSTEM_PROMPT = (
    "You are a context-summarization assistant. "
    "Summarize the conversation so it can be continued with full context. "
    "Preserve: the original goal, key decisions made, current state of the work, "
    "open tasks remaining, and any important file paths or identifiers. "
    "Be concise but complete. Write in plain text, no headers needed."
)


def _build_summarizer_args() -> list[str]:
    return [
        "claude", "--print",
        "--input-format", "stream-json",
        "--output-format", "stream-json",
        "--include-partial-messages", "--verbose",
        "--disallowed-tools", "AskUserQuestion",
        "--append-system-prompt", _SUMMARIZE_SYSTEM_PROMPT,
    ]


def _encode_user_message(text: str) -> bytes:
    payload = {
        "type": "user",
        "message": {"role": "user", "content": [{"type": "text", "text": text}]},
    }
    return (json.dumps(payload) + "\n").encode("utf-8")


async def _spawn_summarizer_proc() -> asyncio.subprocess.Process:
    """Spawn the summarizer process. Injectable for tests."""
    return await asyncio.create_subprocess_exec(
        *_build_summarizer_args(),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=session_store.DEFAULT_CWD,
        env=session_manager.subscription_env(),
    )


def assemble_transcript_text(name: str) -> str:
    """Read all user+assistant turns and join as readable text.

    Uses Claude JSONL when present, else the bridge-owned transcript (Cursor).
    Caps at _TRANSCRIPT_CHAR_CAP characters (tail-biased).
    """
    turns = session_store.read_transcript_turns(name, limit=500)
    if not turns:
        return ""

    parts = [f"[{t['role'].upper()}]\n{t['text']}" for t in turns if t.get("text")]
    full = "\n\n".join(parts)
    if len(full) > _TRANSCRIPT_CHAR_CAP:
        full = "[...transcript truncated...]\n\n" + full[-_TRANSCRIPT_CHAR_CAP:]
    return full


def _entry_text(entry: dict) -> str:
    """Extract plain text from a transcript message entry."""
    content = entry.get("message", {}).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
        return " ".join(p for p in parts if p)
    return ""


async def _collect_summarizer_output(proc: asyncio.subprocess.Process) -> str:
    """Stream text_delta events from the summarizer process and join them."""
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


async def summarize_transcript(transcript_text: str, extra: str) -> str | None:
    """Send the transcript to a one-shot claude process and return the summary text.

    Returns None if the process fails, times out, or returns empty output.
    ``extra`` is optional user-supplied instructions appended to the prompt.
    """
    prompt = f"Summarize this conversation:\n\n{transcript_text}"
    if extra:
        prompt += f"\n\nAdditional focus: {extra}"

    proc: asyncio.subprocess.Process | None = None
    try:
        proc = await _spawn_summarizer_proc()
        assert proc.stdin is not None
        proc.stdin.write(_encode_user_message(prompt))
        await proc.stdin.drain()
        proc.stdin.close()
        summary = await asyncio.wait_for(
            _collect_summarizer_output(proc),
            timeout=_SUMMARIZE_TIMEOUT_S,
        )
        return summary.strip() or None
    except asyncio.TimeoutError:
        logger.warning("compact: summarizer timed out after %.0fs", _SUMMARIZE_TIMEOUT_S)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("compact: summarizer failed: %s", exc)
        return None
    finally:
        if proc is not None and proc.returncode is None:
            try:
                proc.terminate()
            except ProcessLookupError:
                pass


def _format_real_summary_preamble(summary: str) -> str:
    return (
        "[Bridge compact] The conversation was summarized by a one-shot process "
        "before this session was reset. Full summary:\n\n"
        f"{summary}\n\n"
        "Continue from here. Ask me if you need anything that was lost."
    )


def _format_fallback_preamble(fallback: str | None) -> str:
    if not fallback:
        return (
            "[Bridge compact] The session was reset. "
            "No transcript was available to summarize."
        )
    return fallback


def _format_transcript_tail_preamble(transcript_text: str) -> str:
    """Fallback that keeps the raw recent transcript when the summarizer failed.

    Preserves far more context than build_recovery_preamble's last 3 user / 2
    assistant turns — the model reads the actual recent conversation verbatim.
    """
    tail = transcript_text[-_FALLBACK_TRANSCRIPT_TAIL_CHARS:]
    if len(transcript_text) > _FALLBACK_TRANSCRIPT_TAIL_CHARS:
        tail = "[...earlier conversation omitted...]\n\n" + tail
    return (
        "[Bridge compact] The automatic summarizer was unavailable, so the recent "
        "conversation is included verbatim below. Continue the SAME thread from here "
        "— do not restart or ask what the task was unless it is genuinely ambiguous.\n\n"
        f"{tail}"
    )


async def _summarize_with_retry(transcript_text: str, extra: str) -> str | None:
    """Call the summarizer up to _SUMMARIZE_MAX_ATTEMPTS times before giving up."""
    for attempt in range(1, _SUMMARIZE_MAX_ATTEMPTS + 1):
        summary = await summarize_transcript(transcript_text, extra)
        if summary:
            return summary
        logger.warning(
            "compact: summarizer attempt %d/%d produced no summary",
            attempt,
            _SUMMARIZE_MAX_ATTEMPTS,
        )
    return None


def persist_session_notes(name: str, preamble: str, was_real_summary: bool) -> Path | None:
    """Write the latest compact preamble to ~/.dev-bridge/notes/<session>.md."""
    if not preamble.strip():
        return None
    notes_dir = session_store.BRIDGE_DIR / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)
    path = notes_dir / f"{name}.md"
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    header = (
        f"# DevScope session notes — {name}\n\n"
        f"Updated: {stamp}\n"
        f"Summary quality: {'full' if was_real_summary else 'fallback'}\n\n"
    )
    path.write_text(header + preamble.strip() + "\n", encoding="utf-8")
    logger.info("compact: persisted session notes to %s", path)
    return path


async def do_compact(name: str, extra: str) -> tuple[str, bool]:
    """Produce a compact preamble for session ``name``.

    Returns (preamble, was_real_summary).
    - If a full transcript exists and the summarizer succeeds: real summary, True.
    - Otherwise: build_recovery_preamble fallback text, False.
    ``extra`` is forwarded to the summarizer as additional instructions.
    """
    transcript_text = assemble_transcript_text(name)
    if transcript_text:
        summary = await _summarize_with_retry(transcript_text, extra)
        if summary:
            return _format_real_summary_preamble(summary), True
        # Summarizer failed — keep the raw transcript tail rather than a thin extract.
        return _format_transcript_tail_preamble(transcript_text), False

    # No transcript at all: last-resort first-user / last-assistant extract.
    fallback = session_manager.build_recovery_preamble(name)
    return _format_fallback_preamble(fallback), False


# ─────────────────────────────────────────────
# A7: serialized, non-destructive-on-failure compact
# ─────────────────────────────────────────────
# One shared per-session lock used by every caller that can trigger a compact
# — POST /compact (main.py), the /compact slash command (builtin_commands.py),
# and auto-compact (chat_session_hygiene._run_auto_compact). A second caller
# while one is in flight no-ops instead of racing it (RC-5/RC-6: concurrent
# compacts used to be possible; a failed summarizer still wiped session_id +
# transcript). Wraps do_compact() (kept unchanged, still directly tested) with
# the lock, an abort-on-failure guard, and the AgentActivity("Compacting
# session…") start/done/error frames.

_compact_locks: dict[str, asyncio.Lock] = {}


def _get_compact_lock(name: str) -> asyncio.Lock:
    lock = _compact_locks.get(name)
    if lock is None:
        lock = asyncio.Lock()
        _compact_locks[name] = lock
    return lock


@dataclass
class CompactRun:
    """Outcome of guarded_compact(). ok=False means: do NOT touch the session —
    no clear_session_id, no kill_session, no reset_bridge_transcript."""
    ok: bool
    preamble: str = ""
    was_real_summary: bool = False
    skipped: str | None = None  # "already_compacting" | "summarizer_failed"


def _compact_activity(name: str, status: str, detail: str | None = None) -> AgentActivity:
    return AgentActivity(
        session=name, label="Compacting session…", call_id=f"compact:{name}",
        status=status, detail=detail,
    )


async def guarded_compact(name: str, extra: str, q: asyncio.Queue) -> CompactRun:
    """Run do_compact() under a per-session lock; abort destructively-unsafe outcomes.

    - Already compacting: returns ok=False, skipped="already_compacting".
    - A real transcript existed but the summarizer produced nothing after
      retries: returns ok=False, skipped="summarizer_failed" — the caller must
      leave the session exactly as it was (RC-6: this used to still wipe
      session_id/transcript on a failed summarizer).
    - Otherwise: ok=True with the preamble to apply via apply_compact_reset().
    """
    lock = _get_compact_lock(name)
    if lock.locked():
        await q.put(_compact_activity(name, "error", "Already compacting — try again shortly."))
        return CompactRun(ok=False, skipped="already_compacting")

    async with lock:
        await q.put(_compact_activity(name, "running"))
        transcript_text = assemble_transcript_text(name)
        preamble, was_real = await do_compact(name, extra)
        if not was_real and transcript_text:
            logger.warning(
                "compact: '%s' summarizer produced no summary — aborting, "
                "session left intact", name,
            )
            await q.put(_compact_activity(
                name, "error",
                "Summarizer produced no summary — nothing was reset. Try again.",
            ))
            return CompactRun(ok=False, skipped="summarizer_failed")
        await q.put(_compact_activity(name, "done"))
        return CompactRun(ok=True, preamble=preamble, was_real_summary=was_real)


async def apply_compact_reset(name: str, preamble: str, was_real_summary: bool) -> None:
    """Destructive reset after a successful compact — only call when ok=True.

    Never call this for a guarded_compact() outcome with ok=False.
    """
    persist_session_notes(name, preamble, was_real_summary)
    entry = session_store.get_session(name)
    agent = entry.get("agent", "claude") if entry else "claude"
    if agent == "claude":
        session_store.clear_session_id(name)
        await session_manager.kill_session(name)
    session_reader.reset_session_usage(name)
    from devscope_bridge import builtin_commands as _builtins
    _builtins.pending_compact_preambles[name] = preamble
    seed = [{"role": "assistant", "text": preamble}] if preamble.strip() else []
    session_store.reset_bridge_transcript(name, seed_turns=seed)
