"""
session_store.py — Read/write ~/.dev-bridge/sessions.json.

Maps session-name -> {session_id, created_at, last_used, agent, cwd}.

v1 schema additions (agent, cwd) are optional for backwards compatibility.
Old entries without those fields load with defaults: agent="claude",
cwd=DEFAULT_CWD (the original hardcoded project root).
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

BRIDGE_DIR = Path.home() / ".dev-bridge"
SESSIONS_FILE = BRIDGE_DIR / "sessions.json"
BRIDGE_TRANSCRIPTS_DIR = BRIDGE_DIR / "chat-transcripts"

# Fallback for entries lacking a cwd. DEVSCOPE_DEFAULT_CWD wins; otherwise the
# bridge's own working directory (the repo it was launched from) — never a
# hardcoded developer path, this ships as a product.
DEFAULT_CWD = os.environ.get("DEVSCOPE_DEFAULT_CWD") or os.getcwd()
DEFAULT_AGENT = "claude"


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _ensure_dir() -> None:
    BRIDGE_DIR.mkdir(parents=True, exist_ok=True)


def _apply_defaults(entry: dict) -> dict:
    """Fill in v1/v2 fields with safe defaults for old entries missing them."""
    entry.setdefault("agent", DEFAULT_AGENT)
    entry.setdefault("cwd", DEFAULT_CWD)
    entry.setdefault("mode", None)
    entry.setdefault("model", None)
    entry.setdefault("claude_agent", None)
    entry.setdefault("purpose", "chat")
    return entry


def load_sessions() -> dict[str, dict]:
    """Return all persisted sessions. Returns {} if file missing or corrupt."""
    if not SESSIONS_FILE.exists():
        return {}
    try:
        raw: dict[str, dict] = json.loads(SESSIONS_FILE.read_text())
        return {name: _apply_defaults(entry) for name, entry in raw.items()}
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("sessions.json unreadable, starting fresh: %s", exc)
        return {}


def save_sessions(sessions: dict[str, dict]) -> None:
    _ensure_dir()
    SESSIONS_FILE.write_text(json.dumps(sessions, indent=2, ensure_ascii=False))


def get_session(name: str) -> dict | None:
    """Return the stored entry for name (with defaults applied), or None if not found."""
    return load_sessions().get(name)


def get_metadata(name: str) -> dict | None:
    """Return the full entry including agent and cwd, or None if not found."""
    return load_sessions().get(name)


def session_id_owner(session_id: str) -> str | None:
    """Return the DevScope session name that owns `session_id`, or None."""
    if not session_id:
        return None
    for name, entry in load_sessions().items():
        if entry.get("session_id") == session_id:
            return name
    return None


def repair_duplicate_session_ids() -> list[str]:
    """Clear session_id on duplicate owners, keeping the most recently used entry."""
    sessions = load_sessions()
    by_uuid: dict[str, list[str]] = {}
    for name, entry in sessions.items():
        sid = entry.get("session_id") or ""
        if sid:
            by_uuid.setdefault(sid, []).append(name)

    cleared: list[str] = []
    for sid, names in by_uuid.items():
        if len(names) < 2:
            continue
        names.sort(key=lambda n: sessions[n].get("last_used") or "", reverse=True)
        for duplicate in names[1:]:
            sessions[duplicate]["session_id"] = ""
            cleared.append(duplicate)
            logger.warning(
                "Cleared duplicate session_id %s from '%s' (kept '%s')",
                sid, duplicate, names[0],
            )
    if cleared:
        save_sessions(sessions)
    return cleared


def set_session_model(name: str, model: str | None) -> None:
    """Persist model for a session; None clears to CLI default."""
    sessions = load_sessions()
    entry = sessions.get(name)
    if entry is None:
        raise KeyError(name)
    if model:
        entry["model"] = model
    else:
        entry.pop("model", None)
    save_sessions(sessions)


def set_session_claude_agent(name: str, claude_agent: str | None) -> None:
    """Persist Claude subagent slug (--agent); None clears to default agent."""
    sessions = load_sessions()
    entry = sessions.get(name)
    if entry is None:
        raise KeyError(name)
    if claude_agent:
        entry["claude_agent"] = claude_agent
    else:
        entry.pop("claude_agent", None)
    save_sessions(sessions)


def upsert_session(
    name: str,
    session_id: str,
    agent: str | None = None,
    cwd: str | None = None,
    mode: str | None = None,
    model: str | None = None,
) -> None:
    """Create or touch last_used for a named session.

    Optional fields are only written when provided (non-None).
    Existing call sites that pass only (name, session_id) continue to work.

    Refuses to assign a Claude UUID already owned by a different DevScope session.
    """
    if session_id:
        owner = session_id_owner(session_id)
        if owner is not None and owner != name:
            logger.warning(
                "session_id %s already owned by '%s' — not assigning to '%s'",
                session_id, owner, name,
            )
            return
    sessions = load_sessions()
    existing = sessions.get(name)
    if existing:
        sessions[name]["last_used"] = _now_str()
        sessions[name]["session_id"] = session_id
        if agent is not None:
            sessions[name]["agent"] = agent
        if cwd is not None:
            sessions[name]["cwd"] = cwd
        if mode is not None:
            sessions[name]["mode"] = mode
        if model is not None:
            sessions[name]["model"] = model
    else:
        entry: dict = {
            "session_id": session_id,
            "created_at": _now_str(),
            "last_used": _now_str(),
            "agent": agent if agent is not None else DEFAULT_AGENT,
            "cwd": cwd if cwd is not None else DEFAULT_CWD,
            "mode": mode,
            "model": model,
        }
        sessions[name] = entry
    save_sessions(sessions)
    logger.info("Session '%s' upserted: %s", name, session_id)


def create_session_metadata(
    name: str,
    agent: str,
    cwd: str,
    mode: str | None = None,
    model: str | None = None,
    purpose: str | None = None,
) -> dict:
    """Persist a new session entry with agent/cwd/mode/model but no session_id yet.

    Called by POST /sessions. Returns the created entry.
    Does not overwrite an existing entry (caller must check first).
    """
    sessions = load_sessions()
    entry: dict = {
        "session_id": "",
        "created_at": _now_str(),
        "last_used": _now_str(),
        "agent": agent,
        "cwd": cwd,
        "mode": mode,
        "model": model,
        "purpose": purpose or "chat",
    }
    sessions[name] = entry
    save_sessions(sessions)
    logger.info(
        "Session '%s' metadata created (agent=%s, cwd=%s, mode=%s, model=%s, purpose=%s)",
        name, agent, cwd, mode, model, entry["purpose"],
    )
    return entry


def delete_session(name: str) -> bool:
    """Remove a session entry. Returns True if it existed."""
    sessions = load_sessions()
    if name not in sessions:
        return False
    del sessions[name]
    save_sessions(sessions)
    logger.info("Session '%s' deleted from store", name)
    return True


def touch_session(name: str) -> None:
    """Update last_used timestamp without changing session_id."""
    sessions = load_sessions()
    if name in sessions:
        sessions[name]["last_used"] = _now_str()
        save_sessions(sessions)


def transcript_path(name: str) -> str | None:
    """Locate a session's Claude CLI transcript JSONL (the full conversation record).

    Claude Code persists transcripts at ~/.claude/projects/<proj>/<session_id>.jsonl.
    We glob by session_id so we don't depend on the cwd-encoding scheme.
    Returns None when the session has no id or no transcript file exists.
    """
    entry = get_session(name)
    session_id = entry["session_id"] if entry else None
    if not session_id:
        return None
    matches = list((Path.home() / ".claude" / "projects").glob(f"*/{session_id}.jsonl"))
    return str(matches[0]) if matches else None


def _entry_text(entry: dict) -> str:
    """Plain text of a transcript message entry (string or content-block list)."""
    content = entry.get("message", {}).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
        return "\n".join(p for p in parts if p)
    return ""


def bridge_transcript_path(name: str) -> Path:
    """Per-session bridge-owned transcript (Cursor + recovery fallback for all agents)."""
    safe = name.replace("/", "_")
    return BRIDGE_TRANSCRIPTS_DIR / f"{safe}.jsonl"


def append_bridge_turn(name: str, role: str, text: str) -> None:
    """Append one user/assistant turn to the bridge transcript file."""
    cleaned = (text or "").strip()
    if not cleaned or role not in ("user", "assistant"):
        return
    path = bridge_transcript_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {"role": role, "text": cleaned, "ts": _now_str()}
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


# Parsed-transcript cache keyed by file path → (mtime, size, parsed turns).
# The extension polls /transcript for every session repeatedly; without this we
# re-read and json.loads multi-MB JSONL files on each poll, which starves the
# asyncio loop and triggers heavy GC. We reparse only when the file changed.
_TRANSCRIPT_CACHE: dict[str, tuple[float, int, list[dict]]] = {}
_TRANSCRIPT_CACHE_MAX = 256


def _cached_parse(path: Path, parse_line) -> list[dict]:
    """Parse a JSONL transcript, memoized on (mtime, size)."""
    key = str(path)
    try:
        st = path.stat()
    except OSError:
        _TRANSCRIPT_CACHE.pop(key, None)
        return []
    cached = _TRANSCRIPT_CACHE.get(key)
    if cached and cached[0] == st.st_mtime and cached[1] == st.st_size:
        return cached[2]
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    turns: list[dict] = []
    for line in lines:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        turn = parse_line(entry)
        if turn:
            turns.append(turn)
    if len(_TRANSCRIPT_CACHE) >= _TRANSCRIPT_CACHE_MAX:
        _TRANSCRIPT_CACHE.pop(next(iter(_TRANSCRIPT_CACHE)), None)
    _TRANSCRIPT_CACHE[key] = (st.st_mtime, st.st_size, turns)
    return turns


def _parse_bridge_line(entry: dict) -> dict | None:
    role = entry.get("role")
    text = (entry.get("text") or "").strip()
    if role in ("user", "assistant") and text:
        return {"role": role, "text": text}
    return None


# Machinery "user" entries the CLI writes into its JSONL that were never typed
# by the human: interrupt/auto-continue pairs, background-agent notifications,
# permission-approval echoes, compact continuations, skill preambles. They must
# not surface as conversation turns — the panel coalesces consecutive assistant
# events into one bubble per turn, and a machinery entry wedged between them
# splits one turn into two, so count-based transcript merges re-append the first
# half as a duplicate bubble (the "old messages pop up after I send" bug).
_MACHINERY_USER_EXACT = frozenset({
    "Continue from where you left off.",
    "Continue from where you left off",
})
_MACHINERY_USER_PREFIXES = (
    "[Request interrupted by user",
    "<task-notification>",
    "The user approved running",
    "This session is being continued from a previous conversation",
    "Base directory for this skill:",
    "The previous response failed to produce a valid tool call",
)

# End-of-context markers used by the composed-prompt format (see the panel's
# stripContextPreamble): a hard-capped preamble loses its END marker and ends
# with "[context truncated]" instead.
_CONTEXT_END_MARKERS = ("--- END CONTEXT ---", "[context truncated]")
_COMPACT_SEED_PREFIX = "[Bridge compact]"


def _is_machinery_user_text(text: str) -> bool:
    """True for CLI/bridge-generated user entries that are not real user turns."""
    return text in _MACHINERY_USER_EXACT or text.startswith(_MACHINERY_USER_PREFIXES)


def _extract_user_text_from_compact_seed(text: str) -> str:
    """A '[Bridge compact]' user entry is summary + PAGE CONTEXT + the real user
    message. Return that message, or '' when the seed carries no user prompt —
    the summary itself must never surface as a user turn."""
    for marker in _CONTEXT_END_MARKERS:
        idx = text.rfind(marker)
        if idx != -1:
            return text[idx + len(marker):].strip()
    return ""


def _parse_claude_line(entry: dict) -> dict | None:
    role = entry.get("type")
    if role not in ("user", "assistant"):
        return None
    text = _entry_text(entry).strip()
    if not text:
        return None
    if role == "user":
        if text.startswith(_COMPACT_SEED_PREFIX):
            text = _extract_user_text_from_compact_seed(text)
            if not text:
                return None
        elif _is_machinery_user_text(text):
            return None
    return {"role": role, "text": text}


def _read_bridge_turns(name: str) -> list[dict]:
    return _cached_parse(bridge_transcript_path(name), _parse_bridge_line)


def _read_claude_turns(name: str, limit: int) -> list[dict]:
    path = transcript_path(name)
    if not path:
        return []
    return _cached_parse(Path(path), _parse_claude_line)[-limit:]


def read_transcript_turns(name: str, limit: int = 300) -> list[dict]:
    """Return conversation turns — Claude JSONL when present, else bridge transcript."""
    claude_turns = _read_claude_turns(name, limit)
    if claude_turns:
        return claude_turns
    return _read_bridge_turns(name)[-limit:]


def sync_bridge_transcript(name: str, turns: list[dict]) -> None:
    """Replace bridge transcript when the UI has more history (Cursor backfill)."""
    cleaned: list[dict] = []
    for turn in turns:
        role = turn.get("role")
        text = (turn.get("text") or "").strip()
        if role in ("user", "assistant") and text:
            cleaned.append({"role": role, "text": text[:8000]})
    if not cleaned:
        return
    existing = _read_bridge_turns(name)
    if len(cleaned) <= len(existing):
        return
    path = bridge_transcript_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for entry in cleaned:
            fh.write(json.dumps({**entry, "ts": _now_str()}, ensure_ascii=False) + "\n")
    logger.info("Session '%s' bridge transcript synced (%d turns)", name, len(cleaned))


def transcript_ends_incomplete(name: str) -> bool:
    """True if the session's transcript ends on a USER turn with no assistant reply.

    A `claude --resume` on such a conversation tries to replay the dangling turn
    and hangs — so callers clear the session_id and start fresh (the chat picks
    up context via the recovery preamble instead).
    """
    path = transcript_path(name)
    if not path:
        return False
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return False
    last_role = None
    for line in lines:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("type") in ("user", "assistant"):
            last_role = entry["type"]
    return last_role == "user"


def reset_bridge_transcript(name: str, *, seed_turns: list[dict] | None = None) -> None:
    """Replace bridge transcript after /compact or /new.

    Without this, ``read_transcript_turns`` keeps the full pre-compact history on
    disk. Recovery preambles and the next summarizer pass would re-inject stale
    context even though the Claude CLI session was killed and restarted.
    """
    path = bridge_transcript_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for entry in seed_turns or []:
            role = entry.get("role")
            text = (entry.get("text") or "").strip()
            if role in ("user", "assistant") and text:
                fh.write(
                    json.dumps({"role": role, "text": text[:8000], "ts": _now_str()}, ensure_ascii=False)
                    + "\n"
                )
    logger.info(
        "Session '%s' bridge transcript reset (%d seed turns)",
        name,
        len(seed_turns or []),
    )


def clear_session_id(name: str) -> None:
    """Reset session_id to empty string for name, preserving all other metadata.

    Called after a hard-cap forced kill so the next spawn does NOT use --resume
    on a conversation that was left in an incomplete state by the SIGINT.
    """
    sessions = load_sessions()
    if name in sessions:
        sessions[name]["session_id"] = ""
        sessions[name]["last_used"] = _now_str()
        save_sessions(sessions)
        logger.info("Session '%s' session_id cleared (hard-cap respawn)", name)
