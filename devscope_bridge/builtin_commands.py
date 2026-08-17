"""
builtin_commands.py — Bridge-side builtin slash-command handlers.

These commands are dispatched in the WS receive loop BEFORE the prompt reaches
the Claude CLI stdin, because in --print/stream-json mode the CLI does NOT
interpret slash commands.  Each handler emits a SlashCommandCard onto the
session's out_queue so the extension can render a native panel card.

Implemented commands:
  /usage (/cost /context), /model, /memory, /compact, /new
  /status   — session info card (bridge-side)
  /add-dir  — persist extra working dir in session metadata (bridge-side)

Interactive-only stubs (/doctor, /diff, etc.) are declared in commands_scanner.py
and rejected here; the extension also prevents selecting them.

/compact and /new share a side-channel (_pending_compact_preambles) that the
WS receive loop in main.py reads before the next run_prompt() call so the fresh
process gets the recovery preamble injected as pending_preamble — identical to
what _watchdog_respawn does.
"""

import asyncio
import os
from pathlib import Path

from devscope_bridge import compact_service, session_manager, session_store, session_reader
from devscope_bridge import status_helpers
from devscope_bridge.models import SlashCommandCard

# Module-level side-channel: preambles stashed by /compact or /new, consumed
# once by the WS receive loop right before the next run_prompt call.
pending_compact_preambles: dict[str, str] = {}


def format_usage_body(usage: dict, session_name: str) -> str:
    """Build a human-readable usage report from accumulated session stats."""
    inp = usage["input_tokens"]
    out = usage["output_tokens"]
    cache_r = usage["cache_read_tokens"]
    cache_w = usage["cache_write_tokens"]
    total_tokens = inp + out
    cost = usage["cost_usd"]
    turns = usage["turn_count"]
    lines = [
        f"Session: {session_name}  |  Turns: {turns}",
        f"Input tokens:        {inp:>10,}",
        f"Output tokens:       {out:>10,}",
    ]
    if cache_r or cache_w:
        lines.append(f"Cache read tokens:   {cache_r:>10,}")
        lines.append(f"Cache write tokens:  {cache_w:>10,}")
    lines.append(f"Total tokens:        {total_tokens:>10,}")
    lines.append(f"Estimated cost:      ${cost:.4f} USD")
    return "\n".join(lines)


def read_memory_files(project_root: str) -> list[dict]:
    """Read CLAUDE.md and user memory index files.

    Returns a list of {path, label, content} dicts for every file that exists.
    Content is capped at 2000 chars to stay within a readable card.
    """
    files: list[dict] = []
    root = Path(project_root)
    home = Path.home()
    # Build the expected memory-index path from the project root's name.
    # ~/.claude/projects/-Users-…-ProjectName/memory/MEMORY.md
    project_key = str(root).replace("/", "-").lstrip("-")
    candidates = [
        (root / "CLAUDE.md", "Project: CLAUDE.md"),
        (home / ".claude" / "projects" / project_key / "memory" / "MEMORY.md",
         "User memory index"),
        (home / ".claude" / "CLAUDE.md", "User: ~/.claude/CLAUDE.md"),
    ]
    for path, label in candidates:
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            files.append({"path": str(path), "label": label, "content": text[:2000]})
        except OSError:
            pass
    return files


async def handle_usage(session_name: str, q: asyncio.Queue) -> None:
    """Emit a token-usage card for the current session."""
    usage = session_reader.get_session_usage(session_name)
    body = format_usage_body(usage, session_name)
    await q.put(SlashCommandCard(
        session=session_name,
        kind="usage",
        title="Token usage",
        body=body,
        data=dict(usage),
    ))


def apply_session_claude_agent(session_name: str, claude_agent: str | None) -> str | None:
    """Persist subagent slug and update the live subprocess slot (respawn on next turn)."""
    session_store.set_session_claude_agent(session_name, claude_agent)
    active = session_manager._sessions.get(session_name)
    if active is not None:
        active.claude_agent = claude_agent
    return claude_agent


def apply_session_model(session_name: str, new_model: str | None) -> str | None:
    """Persist model and update the live subprocess slot (respawn on next turn)."""
    session_store.set_session_model(session_name, new_model)
    active = session_manager._sessions.get(session_name)
    if active is not None:
        active.model = new_model
    return new_model


def current_session_model(session_name: str) -> str | None:
    active = session_manager._sessions.get(session_name)
    if active is not None:
        return active.model
    meta = session_store.get_metadata(session_name) or {}
    return meta.get("model")


async def handle_model(session_name: str, prompt: str, q: asyncio.Queue) -> None:
    """Show or switch the model for the current session."""
    parts = prompt.split(maxsplit=1)
    new_model = parts[1].strip() if len(parts) > 1 else ""
    if not new_model:
        current = current_session_model(session_name)
        entry = session_store.get_session(session_name) or {}
        agent = entry.get("agent", "claude")
        display = current if current else "Default (account)"
        agent_note = (
            "cursor-agent uses --model on the next turn."
            if agent == "cursor"
            else "Claude CLI uses --model on the next message."
        )
        await q.put(SlashCommandCard(
            session=session_name,
            kind="model",
            title="Current model",
            body=(
                f"Active model: {display}\n"
                f"{agent_note}\n"
                "Pick in the composer model pill or: /model <name>"
            ),
            data={"model": current},
        ))
        return

    apply_session_model(session_name, new_model)
    await q.put(SlashCommandCard(
        session=session_name,
        kind="model",
        title="Model updated",
        body=f"Switched to: {new_model}\nThe new model takes effect on the next message.",
        data={"model": new_model},
    ))


async def handle_memory(session_name: str, q: asyncio.Queue) -> None:
    """Surface loaded memory files as a read-only card."""
    cwd = session_manager._session_cwd(session_name)
    files = read_memory_files(cwd)
    if not files:
        body = "No CLAUDE.md or memory index found for this session."
    else:
        parts_list = []
        for f in files:
            parts_list.append(f"── {f['label']} ({f['path']}) ──")
            parts_list.append(f['content'])
        body = "\n\n".join(parts_list)
    await q.put(SlashCommandCard(
        session=session_name,
        kind="memory",
        title="Memory context",
        body=body,
        data={"files": [{"label": f["label"], "path": f["path"]} for f in files]},
    ))


async def handle_compact(session_name: str, prompt: str, q: asyncio.Queue) -> None:
    """Summarise the full conversation and respawn the CLI session with the summary as preamble.

    Emits a "Compacting..." card immediately, then runs a one-shot claude summarizer
    against the full transcript.  Falls back to a brief recovery note when the
    transcript is missing, and labels the card honestly.

    A7: serialized with POST /compact and auto-compact via the SAME per-session
    lock (compact_service.guarded_compact) — a concurrent compact or a
    summarizer failure on a real transcript skips the destructive reset
    entirely instead of wiping session_id/transcript (RC-5/RC-6).
    """
    parts = prompt.split(maxsplit=1)
    extra = parts[1].strip() if len(parts) > 1 else ""

    await q.put(SlashCommandCard(
        session=session_name,
        kind="compact",
        title="Compacting…",
        body="Summarizing conversation — this may take a few seconds.",
        data={"status": "in_progress"},
    ))

    result = await compact_service.guarded_compact(session_name, extra, q)
    if not result.ok:
        await q.put(SlashCommandCard(
            session=session_name,
            kind="compact",
            title="Compact skipped",
            body=(
                "Already compacting this session — try again shortly."
                if result.skipped == "already_compacting"
                else "Could not summarize — nothing was reset. Try again."
            ),
            data={"skipped": result.skipped},
        ))
        return

    await compact_service.apply_compact_reset(session_name, result.preamble, result.was_real_summary)

    if result.was_real_summary:
        title = "Conversation compacted"
        body = (
            "Claude CLI restarted with the summary only. "
            "Panel history stays visible for you — it is not sent again."
        )
    else:
        title = "Conversation compacted (fallback)"
        body = (
            "Could not generate a full summary (no transcript); "
            "kept a brief recovery note instead. The next message will include it."
        )
    await q.put(SlashCommandCard(
        session=session_name,
        kind="compact",
        title=title,
        body=body,
        data={"was_real_summary": result.was_real_summary},
    ))


async def handle_status(session_name: str, q: asyncio.Queue) -> None:
    """Emit a session/CLI status card (no model turn)."""
    cli_version = await status_helpers.get_cli_version()
    body = status_helpers.build_status_body(session_name, cli_version)
    await q.put(SlashCommandCard(
        session=session_name,
        kind="status",
        title="Session status",
        body=body,
        data={"cli_version": cli_version},
    ))


async def handle_add_dir(session_name: str, prompt: str, q: asyncio.Queue) -> None:
    """Persist an extra working directory in session metadata.

    Validates the path exists, then writes it to the session store under the
    'extra_dirs' list and marks the session for respawn so the next spawn
    forwards --add-dir to the Claude CLI subprocess.
    """
    parts = prompt.split(maxsplit=1)
    raw_path = parts[1].strip() if len(parts) > 1 else ""
    if not raw_path:
        await q.put(SlashCommandCard(
            session=session_name,
            kind="add_dir",
            title="Usage: /add-dir <path>",
            body="Provide an absolute path to add as a working directory.",
            data={"valid": False},
        ))
        return

    path = os.path.expanduser(raw_path)
    if not os.path.isdir(path):
        await q.put(SlashCommandCard(
            session=session_name,
            kind="add_dir",
            title="Path not found",
            body=f"{raw_path}\nThe directory does not exist or is not a directory.",
            data={"path": raw_path, "valid": False},
        ))
        return

    stored = session_store.get_session(session_name)
    existing: list[str] = (stored or {}).get("extra_dirs") or []
    if path in existing:
        await q.put(SlashCommandCard(
            session=session_name,
            kind="add_dir",
            title="Already added",
            body=f"{path} is already in the extra working directories.",
            data={"path": path, "valid": True},
        ))
        return

    if stored is not None:
        sessions = session_store.load_sessions()
        if session_name in sessions:
            sessions[session_name]["extra_dirs"] = existing + [path]
            session_store.save_sessions(sessions)

    active = session_manager._sessions.get(session_name)
    if active is not None:
        active.pending_respawn = True

    await q.put(SlashCommandCard(
        session=session_name,
        kind="add_dir",
        title="Working directory added",
        body=(
            f"Added: {path}\n"
            "Persisted to session metadata. "
            "Takes effect on the next message."
        ),
        data={"path": path, "valid": True},
    ))


async def handle_new(session_name: str, q: asyncio.Queue) -> None:
    """Kill the current session process and start fresh, keeping the session name."""
    session_store.clear_session_id(session_name)
    await session_manager.kill_session(session_name)
    session_reader.reset_session_usage(session_name)
    await q.put(SlashCommandCard(
        session=session_name,
        kind="new",
        title="New conversation started",
        body="The session process has been reset. Chat history is preserved in the panel.",
        data={},
    ))


async def dispatch(
    session_name: str,
    verb: str,
    prompt: str,
    q: asyncio.Queue,
) -> None:
    """Route a bridge builtin command to its handler.

    Handles /usage, /cost, /context, /model, /memory, /compact, /new,
    /status, /add-dir.
    Disabled (terminal-only) stubs emit a brief informational card in case the
    extension's guard fails, but should never reach here in normal operation.
    """
    from devscope_bridge.commands_scanner import DISABLED_BUILTIN_NAMES
    if verb in DISABLED_BUILTIN_NAMES:
        await q.put(SlashCommandCard(
            session=session_name,
            kind="usage",
            title=f"{verb} — terminal only",
            body=f"{verb} is only available in interactive terminal mode, not in DevScope.",
        ))
        return

    if verb in ("/usage", "/cost", "/context"):
        await handle_usage(session_name, q)
    elif verb == "/model":
        await handle_model(session_name, prompt, q)
    elif verb == "/memory":
        await handle_memory(session_name, q)
    elif verb == "/compact":
        await handle_compact(session_name, prompt, q)
    elif verb == "/new":
        await handle_new(session_name, q)
    elif verb == "/status":
        await handle_status(session_name, q)
    elif verb == "/add-dir":
        await handle_add_dir(session_name, prompt, q)
