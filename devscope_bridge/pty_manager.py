"""
pty_manager.py — Real interactive terminals over a pseudo-terminal (PTY).

This is an ADDITIVE capability, fully separate from the stream-json session
model in session_manager.py.  It spawns a command (an interactive `claude`, a
`claude --resume <session_id>` attached to an existing conversation, or a plain
shell) under a real PTY so the panel's xterm.js terminal can render its TUI and
forward keystrokes — letting a human drive a session directly, even one whose
headless --print process went silent.

Loopback + token auth are enforced by the WS endpoint in main.py.  A reader
thread per terminal pumps the master fd into an asyncio.Queue (thread-safe via
call_soon_threadsafe); the WS handler drains it.  Input and window-resize go
straight to the master fd.
"""

import asyncio
import fcntl
import json
import logging
import os
import pty
import re
import signal
import struct
import termios
import threading
import time
from dataclasses import dataclass, field

from devscope_bridge import session_manager, session_store

logger = logging.getLogger(__name__)


class PtyConflictError(RuntimeError):
    """Raised when opening a PTY with --resume would race a live chat turn.

    A6/RC-2: a `claude --resume <session_id>` PTY and the headless chat
    process used to be allowed to run concurrently on the SAME session_id —
    two processes racing the same conversation caused the wedge this fix
    targets. Mirrors the rule session_manager.run_prompt already enforces in
    the opposite direction (closing a live PTY before spawning chat).
    """

_READ_CHUNK = 65536
_FALLBACK_COLS = 80
_FALLBACK_ROWS = 24
_SESSION_ID_RE = re.compile(r'"sessionId"\s*:\s*"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"')
_PTY_SESSIONS_FILE = session_store.BRIDGE_DIR / "pty_sessions.json"


@dataclass
class _Terminal:
    terminal_id: str
    master_fd: int
    pid: int
    out_queue: asyncio.Queue
    reader: threading.Thread
    session_name: str | None = field(default=None)
    cwd: str | None = field(default=None)
    opened_at: float = field(default=0.0)
    output_tail: str = field(default="")
    claude_session_id: str | None = field(default=None)
    closed: bool = field(default=False)


_terminals: dict[str, _Terminal] = {}
_pty_uuid_by_terminal: dict[str, str] = {}


def _load_pty_sessions() -> None:
    global _pty_uuid_by_terminal
    if not _PTY_SESSIONS_FILE.exists():
        _pty_uuid_by_terminal = {}
        return
    try:
        raw = json.loads(_PTY_SESSIONS_FILE.read_text())
        if isinstance(raw, dict):
            _pty_uuid_by_terminal = {str(k): str(v) for k, v in raw.items()}
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("pty_sessions.json unreadable: %s", exc)
        _pty_uuid_by_terminal = {}


def _save_pty_sessions() -> None:
    session_store._ensure_dir()
    _PTY_SESSIONS_FILE.write_text(
        json.dumps(_pty_uuid_by_terminal, indent=2, ensure_ascii=False),
    )


_load_pty_sessions()


def terminal_for_session(session_name: str) -> str | None:
    """Return the terminal_id of a live PTY owning `session_name`, else None."""
    for tid, term in _terminals.items():
        if not term.closed and term.session_name == session_name:
            return tid
    return None


def build_argv(cmd: str, session_name: str | None) -> tuple[list[str], str]:
    """Resolve the (argv, cwd) for a terminal request."""
    cwd = session_store.DEFAULT_CWD
    if cmd == "shell":
        return [os.environ.get("SHELL", "/bin/bash")], cwd
    if session_name:
        meta = session_store.get_metadata(session_name)
        if meta and meta.get("cwd"):
            cwd = meta["cwd"]
    if cmd == "resume" and session_name:
        stored = session_store.get_session(session_name)
        session_id = stored["session_id"] if stored else None
        if session_id:
            return ["claude", "--resume", session_id], cwd
    return ["claude"], cwd


def _pty_env(session_name: str | None) -> dict[str, str]:
    env = session_manager.subscription_env(session_name)
    env["TERM"] = "xterm-256color"
    return env


def _set_winsize(fd: int, cols: int, rows: int) -> None:
    winsize = struct.pack("HHHH", max(1, rows), max(1, cols), 0, 0)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)


def _assign_claude_session_id(terminal_id: str, session_name: str, session_id: str) -> bool:
    """Persist Claude UUID for this terminal/session if not owned elsewhere."""
    if not session_id or not session_name:
        return False
    term = _terminals.get(terminal_id)
    if term is not None and term.claude_session_id == session_id:
        return True
    owner = session_store.session_id_owner(session_id)
    if owner is not None and owner != session_name:
        logger.warning(
            "PTY '%s': Claude session %s owned by '%s', not '%s'",
            terminal_id, session_id, owner, session_name,
        )
        return False
    stored = session_store.get_session(session_name)
    existing = (stored or {}).get("session_id") or ""
    if existing and existing != session_id:
        owner = session_store.session_id_owner(existing)
        if owner == session_name:
            # Already have a different id for this chat — don't steal from another PTY.
            return False
    session_store.upsert_session(session_name, session_id)
    _pty_uuid_by_terminal[terminal_id] = session_id
    _save_pty_sessions()
    if term is not None:
        term.claude_session_id = session_id
    logger.info("PTY '%s' bound session '%s' → Claude %s", terminal_id, session_name, session_id)
    return True


def ingest_pty_output(terminal_id: str, chunk: str) -> None:
    """Parse Claude sessionId from PTY stream and bind it to this terminal only."""
    term = _terminals.get(terminal_id)
    if term is None or term.closed or not term.session_name:
        return
    if term.claude_session_id:
        return
    term.output_tail = (term.output_tail + chunk)[-_READ_CHUNK:]
    for match in _SESSION_ID_RE.finditer(term.output_tail):
        if _assign_claude_session_id(terminal_id, term.session_name, match.group(1)):
            return


def _reader_loop(term_id: str, master_fd: int, loop: asyncio.AbstractEventLoop, q: asyncio.Queue) -> None:
    """Thread: blockingly read the master fd, hand bytes to the event loop."""
    while True:
        try:
            data = os.read(master_fd, _READ_CHUNK)
        except OSError:
            data = b""
        if not data:
            loop.call_soon_threadsafe(q.put_nowait, None)
            return
        text = data.decode("utf-8", errors="replace")
        loop.call_soon_threadsafe(q.put_nowait, text)


def resolve_terminal_params(
    terminal_id: str, cmd: str, session_name: str | None,
) -> tuple[str, str | None]:
    """chat-{session} terminals always resume that session."""
    if terminal_id.startswith("chat-"):
        inferred = terminal_id[5:] or session_name
        return "resume", inferred
    return cmd, session_name


async def open_terminal(
    terminal_id: str,
    cmd: str,
    session_name: str | None,
    *,
    cols: int = _FALLBACK_COLS,
    rows: int = _FALLBACK_ROWS,
) -> _Terminal:
    """Spawn `cmd` under a fresh PTY with the client's winsize."""
    cmd, session_name = resolve_terminal_params(terminal_id, cmd, session_name)
    existing = _terminals.get(terminal_id)
    if existing is not None and not existing.closed:
        logger.info("PTY '%s' replacing live terminal (pid %d)", terminal_id, existing.pid)
        close_terminal(terminal_id)
    if cmd == "resume" and session_name:
        if session_manager.is_turn_running(session_name):
            # A6: refuse instead of spawning `claude --resume <same id>`
            # alongside the running chat turn — that race is what wedged the
            # session (RC-2). No PTY is opened; caller reports the error.
            raise PtyConflictError(
                f"Chat turn in progress on '{session_name}' — try again when "
                "idle, or open a terminal without --resume."
            )
        await session_manager.kill_session(session_name)
        logger.info("PTY '%s' takes over idle session '%s'", terminal_id, session_name)
    argv, cwd = build_argv(cmd, session_name)
    master_fd, slave_fd = pty.openpty()
    try:
        _set_winsize(master_fd, cols, rows)
        _set_winsize(slave_fd, cols, rows)
    except OSError as exc:
        logger.debug("PTY '%s' initial winsize failed: %s", terminal_id, exc)

    opened_at = time.time()
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
        cwd=cwd, env=_pty_env(session_name), start_new_session=True,
        close_fds=True,
    )
    os.close(slave_fd)

    q: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()
    reader = threading.Thread(
        target=_reader_loop, args=(terminal_id, master_fd, loop, q), daemon=True,
    )
    reader.start()

    known_sid = _pty_uuid_by_terminal.get(terminal_id)
    if not known_sid and session_name:
        stored = session_store.get_session(session_name)
        known_sid = (stored or {}).get("session_id") or None

    term = _Terminal(
        terminal_id, master_fd, proc.pid, q, reader,
        session_name=session_name, cwd=cwd, opened_at=opened_at,
        claude_session_id=known_sid or None,
    )
    _terminals[terminal_id] = term
    logger.info(
        "PTY '%s' opened: %s (pid %d, cwd %s, %dx%d)",
        terminal_id, argv, proc.pid, cwd, cols, rows,
    )
    return term


def write_input(terminal_id: str, data: str) -> None:
    term = _terminals.get(terminal_id)
    if term is None or term.closed:
        return
    try:
        os.write(term.master_fd, data.encode("utf-8"))
    except OSError as exc:
        logger.debug("PTY '%s' write failed: %s", terminal_id, exc)


def resize(terminal_id: str, cols: int, rows: int) -> None:
    term = _terminals.get(terminal_id)
    if term is None or term.closed:
        return
    try:
        _set_winsize(term.master_fd, cols, rows)
    except OSError as exc:
        logger.debug("PTY '%s' resize failed: %s", terminal_id, exc)


def close_terminal(terminal_id: str) -> None:
    term = _terminals.pop(terminal_id, None)
    if term is None or term.closed:
        return
    term.closed = True
    if term.session_name and term.claude_session_id:
        _assign_claude_session_id(terminal_id, term.session_name, term.claude_session_id)
    try:
        os.killpg(os.getpgid(term.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        os.close(term.master_fd)
    except OSError:
        pass
    logger.info("PTY '%s' closed", terminal_id)
