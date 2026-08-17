"""
watchdog_medic.py — The Watchdog Medic.

When a dev-bridge session goes silent mid-turn for _WATCHDOG_MEDIC_S (a tier
BELOW the destructive hard-cap), the bridge spawns a SEPARATE claude --print
process — the "medic" — to investigate WHY the turn is stuck.  The medic:

1. Receives a diagnostics bundle (stuck session state + relay state + recent
   event tail) captured by ``collect_diagnostics``.
2. Streams its findings back to the DevScope panel (as AiChunk frames, so it is
   visible in the existing UI, plus structured WatchdogReport frames).
3. May apply a SCOPED code fix — only files under devscope_bridge/ or the
   extension dir — when it finds a clear bug.  Never runs destructive git.

The medic runs on the SAME out_queue as the stuck session so its report appears
inline in the panel.  While a medic is running, the hard-cap watchdog DEFERS the
SIGINT+respawn (see session_reader._watchdog_loop) so the live, stuck process is
not killed out from under the diagnosis.

Isolation: the medic is its own process with its own conversation; it never
writes to the stuck process's stdin.  One medic per session at a time.
"""

import asyncio
import json
import logging
import os
from pathlib import Path

from devscope_bridge import browser_relay
from devscope_bridge import session_manager
from devscope_bridge import session_reader
from devscope_bridge import session_store
from devscope_bridge.models import AgentActivity, AiChunk, WatchdogReport

logger = logging.getLogger(__name__)

# Repo root: devscope_bridge/watchdog_medic.py → parents[1] == this snapshot root.
_REPO_ROOT = Path(__file__).resolve().parents[1]

# Hard ceiling on a medic run so a wedged medic can never run forever.
_MEDIC_RUN_TIMEOUT_S = 150.0

# Permission mode for the medic process.  acceptEdits lets it Read/Grep/Edit/Write
# autonomously (enough to diagnose AND fix code) while still blocking arbitrary
# Bash.  Override to "bypassPermissions" for full autonomy (e.g. git diff / logs).
_MEDIC_PERMISSION_MODE = os.environ.get("DEVSCOPE_MEDIC_PERMISSION_MODE", "acceptEdits")

# Session names with a medic currently running — one medic per session.
_active_medics: set[str] = set()


def is_medic_active(name: str) -> bool:
    """True while a medic is investigating session ``name`` (hard-cap defers)."""
    return name in _active_medics


# ─────────────────────────────────────────────
# Diagnostics
# ─────────────────────────────────────────────

def _resolve_transcript_path(name: str) -> str | None:
    """Claude JSONL path, or bridge-owned transcript for Cursor / fallback."""
    claude_path = session_store.transcript_path(name)
    if claude_path:
        return claude_path
    bridge = session_store.bridge_transcript_path(name)
    if bridge.is_file():
        return str(bridge)
    return None


def collect_diagnostics(name: str, elapsed_s: float, trigger: str = "auto") -> dict:
    """Capture everything we know about a stuck session, without touching it.

    trigger: "auto" (watchdog fired after _WATCHDOG_MEDIC_S of silence — the
    session IS genuinely stuck) or "manual" (a human ran /medic on demand — the
    session may or may not actually be stuck; check turn_done / last_output_at).
    """
    entry = session_store.get_session(name)
    agent = (entry or {}).get("agent") or "claude"
    return {
        "session": name,
        "agent": agent,
        "trigger": trigger,
        "silent_for_s": round(elapsed_s, 1),
        "session_state": session_manager.get_session_state(name),
        "transcript_path": _resolve_transcript_path(name),
        "extension_ws_connected": browser_relay.has_active_ws(name),
        "pending_browser_actions": len(browser_relay._pending_actions),
        "recent_events": session_reader.get_recent_events(name),
    }


# ─────────────────────────────────────────────
# Medic prompt + process
# ─────────────────────────────────────────────

_MEDIC_SYSTEM_PROMPT = (
    "You are the DevScope Watchdog Medic — an automated diagnostic agent. A "
    "DevScope dev-bridge session has gone silent MID-TURN and looks stuck. You "
    "are a SEPARATE process; never touch the stuck process directly.\n\n"
    "The stuck agent is usually a `claude --print` persistent process; Cursor "
    "sessions use one-shot `cursor-agent` subprocesses (agent=\"cursor\" in the "
    "bundle). Common stuck causes: an orphaned browser-action Future (the Chrome "
    "extension disconnected mid-action), a hung Bash/tool call, an infinite tool "
    "loop, an MCP deadlock, or the turn waiting on input it can never get in "
    "headless mode.\n\n"
    "Your job:\n"
    "1. READ THE STUCK SESSION'S TRANSCRIPT FIRST. The diagnostics bundle has a "
    "`transcript_path` — for Claude this is JSONL under ~/.claude/projects/; for "
    "Cursor it is ~/.dev-bridge/chat-transcripts/<session>.jsonl. Read the LAST "
    "entries to see exactly what it was doing when it went silent.\n"
    "2. Diagnose the most likely root cause, combining the transcript with the "
    "rest of the bundle and (if needed) the bridge code under devscope_bridge/.\n"
    "3. Report a SHORT, plain-text root-cause + recommendation (this streams live "
    "to the DevScope panel).\n"
    "4. ONLY if you find a clear code bug, fix it — editing files under "
    "devscope_bridge/ or the extension dir ONLY. Show the exact change.\n\n"
    "Interpreting the trigger:\n"
    "- trigger=\"auto\": the watchdog fired after a long silence — the session is "
    "genuinely stuck mid-turn.\n"
    "- trigger=\"manual\": a human asked you on-demand. The session may NOT be "
    "stuck at all — check session_state.turn_done (true = idle, not stuck) and "
    "last_output_at (vs last_user_msg_at) before assuming a problem. silent_for_s "
    "may be 0 for manual runs.\n\n"
    "Hard rules:\n"
    "- NEVER run destructive git (no reset/checkout/clean/commit/push/rebase). "
    "Read-only git (status/diff/log) is fine.\n"
    "- Do NOT edit anything outside devscope_bridge/ and the extension dir.\n"
    "- Do NOT use browser tools — you have no connected browser.\n"
    "- Be concise and end your turn when done."
)


def _build_medic_args() -> list[str]:
    return [
        "claude", "--print",
        "--input-format", "stream-json",
        "--output-format", "stream-json",
        "--include-partial-messages", "--verbose",
        "--disallowed-tools", "AskUserQuestion",
        "--permission-mode", _MEDIC_PERMISSION_MODE,
        "--append-system-prompt", _MEDIC_SYSTEM_PROMPT,
    ]


def _encode_user_message(text: str) -> bytes:
    payload = {
        "type": "user",
        "message": {"role": "user", "content": [{"type": "text", "text": text}]},
    }
    return (json.dumps(payload) + "\n").encode("utf-8")


async def _spawn_medic_proc() -> asyncio.subprocess.Process:
    """Spawn the medic claude process in the repo root. Injectable for tests."""
    return await asyncio.create_subprocess_exec(
        *_build_medic_args(),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(_REPO_ROOT),
        env=session_manager.subscription_env(),
    )


def _build_medic_prompt(diagnostics: dict) -> str:
    return (
        "A dev-bridge session appears stuck. Diagnose and (only if clearly a "
        "code bug) fix it. Diagnostics bundle:\n\n"
        f"```json\n{json.dumps(diagnostics, indent=2, default=str)}\n```"
    )


async def _stream_medic_output(name: str, proc: asyncio.subprocess.Process, q: asyncio.Queue) -> None:
    """Forward the medic's streamed text to the panel as AiChunk + WatchdogReport."""
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
                    await q.put(AiChunk(session=name, text=text))
                    await q.put(WatchdogReport(session=name, phase="chunk", text=text))
        elif ev_type == "result":
            break


async def run_medic(
    name: str,
    q: asyncio.Queue,
    medic_active: asyncio.Event,
    elapsed_s: float = 0.0,
    trigger: str = "auto",
) -> None:
    """Spawn, stream, and supervise a medic for a stuck session.

    Sets ``medic_active`` for the whole run (so the hard-cap watchdog defers the
    SIGINT+respawn) and clears it in ``finally``.  One medic per session: a second
    call while one is in flight is a no-op.

    trigger: "auto" (watchdog) or "manual" (/medic command) — forwarded to the
    diagnostics bundle so the medic interprets silent_for_s correctly.
    """
    if name in _active_medics:
        if trigger == "manual":
            await q.put(AgentActivity(
                session=name,
                label="🩺 Medic already running",
                detail=(
                    "A diagnosis is already in progress — scroll up for the Medic card. "
                    "Wait for it to finish, or use /reset if the session is wedged."
                ),
            ))
        return
    _active_medics.add(name)
    medic_active.set()
    diagnostics = collect_diagnostics(name, elapsed_s, trigger)
    logger.warning(
        "Watchdog Medic starting for session '%s' (trigger=%s silent=%.0fs)",
        name, trigger, elapsed_s,
    )
    await q.put(WatchdogReport(session=name, phase="start", diagnostics=diagnostics))
    await q.put(AgentActivity(
        session=name, label="🩺 Medic diagnosing…",
        detail=f"Session silent for {elapsed_s:.0f}s — investigating",
    ))
    await q.put(AiChunk(
        session=name,
        text="\n\n---\n🩺 **DevScope Watchdog Medic** — this turn went silent and looks "
             "stuck, so I spawned a separate session to diagnose it.\n\n",
    ))

    proc: asyncio.subprocess.Process | None = None
    try:
        proc = await _spawn_medic_proc()
        assert proc.stdin is not None
        proc.stdin.write(_encode_user_message(_build_medic_prompt(diagnostics)))
        await proc.stdin.drain()
        proc.stdin.close()
        await asyncio.wait_for(_stream_medic_output(name, proc, q), timeout=_MEDIC_RUN_TIMEOUT_S)
        await q.put(WatchdogReport(session=name, phase="done", detail="Medic finished diagnosis."))
        await q.put(AgentActivity(session=name, label="🩺 Medic done"))
        logger.info("Watchdog Medic finished for session '%s'", name)
    except asyncio.TimeoutError:
        await q.put(WatchdogReport(
            session=name, phase="error",
            detail=f"Medic exceeded {_MEDIC_RUN_TIMEOUT_S:.0f}s — aborted.",
        ))
        logger.warning("Watchdog Medic timed out for session '%s'", name)
    except Exception as exc:  # noqa: BLE001 — never let the medic crash the bridge
        await q.put(WatchdogReport(session=name, phase="error", detail=f"Medic failed: {exc}"))
        logger.warning("Watchdog Medic error for session '%s': %s", name, exc)
    finally:
        if proc is not None and proc.returncode is None:
            try:
                proc.terminate()
            except ProcessLookupError:
                pass
        _active_medics.discard(name)
        medic_active.clear()
