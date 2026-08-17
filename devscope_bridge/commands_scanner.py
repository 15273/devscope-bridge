"""
commands_scanner.py — Scan .claude/commands and .claude/skills directories for
slash-command metadata used by the /commands REST endpoint.
"""

from pathlib import Path

from devscope_bridge import session_store

# Built-in commands handled by the bridge itself (not backed by a .md file).
# Fields:
#   name        — slash command string (must start with /)
#   description — shown in the slash menu
#   source      — always "builtin" for bridge-side commands
#   aliases     — optional list of alternate names that resolve to this command
#   disabled    — if True, show greyed-out in menu with a terminal-only note
#   note        — shown instead of the description for disabled commands
_BUILTIN_COMMANDS: list[dict] = [
    {
        "name": "/medic",
        "description": "Diagnose a stuck session — spawns a separate agent. Usage: /medic [session-name]",
        "source": "builtin",
    },
    {
        "name": "/interrupt",
        "description": "Stop the current turn. Context is preserved if the process responds cleanly.",
        "source": "builtin",
    },
    {
        "name": "/ask",
        "description": "Ask a question in parallel without stopping the running turn. Usage: /ask <question>",
        "source": "builtin",
        "parallel": True,
    },
    {
        "name": "/cursor-task",
        "description": (
            "Run Cursor with MCP plugins (Notion, browser, tasks, …) in a side bubble. "
            "Usage: /cursor-task <task>"
        ),
        "source": "builtin",
        "aliases": ["/plugins", "/notion"],
        "parallel": True,
    },
    {
        "name": "/cursor-ctx",
        "description": (
            "Cursor maps the codebase (read-only), then Claude runs your task with that context. "
            "Usage: /cursor-ctx <task>"
        ),
        "source": "builtin",
        "aliases": ["/ctx"],
        "parallel": True,
    },
    {
        "name": "/usage",
        "description": "Show token usage and estimated cost for this session.",
        "source": "builtin",
        "aliases": ["/cost", "/context"],
    },
    {
        "name": "/compact",
        "description": "Summarise the conversation and start fresh with the summary as preamble. Usage: /compact [extra instructions]",
        "source": "builtin",
    },
    {
        "name": "/new",
        "description": "Start a fresh CLI session (new conversation). Chat history is preserved in the panel.",
        "source": "builtin",
    },
    {
        "name": "/model",
        "description": "Switch the model for this session. Usage: /model [model-name]",
        "source": "builtin",
    },
    {
        "name": "/memory",
        "description": "Show what context is loaded: CLAUDE.md and memory index.",
        "source": "builtin",
    },
    {
        "name": "/status",
        "description": "Show active model, session ID, mode, CWD, and CLI version.",
        "source": "builtin",
    },
    {
        "name": "/add-dir",
        "description": "Persist an extra working directory for this session. Usage: /add-dir <path>",
        "source": "builtin",
    },
    {
        "name": "/review",
        "description": "Review the current git diff for bugs, logic errors, and risky changes. Usage: /review [focus]",
        "source": "builtin",
    },
    {
        "name": "/security-review",
        "description": "Security review of the current git diff: injection, authz, secrets, SSRF, path traversal. Usage: /security-review [focus]",
        "source": "builtin",
    },
    {
        "name": "/pr-comments",
        "description": "Summarise unresolved review comments on the current PR. Usage: /pr-comments [PR#]",
        "source": "builtin",
    },
    # ── Interactive-terminal-only stubs ─────────────────────────────────────
    # These are rendered greyed-out in the menu with a note explaining why they
    # are unavailable. They must NOT be forwarded to the CLI — they only work
    # in interactive terminal mode and do nothing (or error) via stream-json.
    {
        "name": "/doctor",
        "source": "builtin",
        "disabled": True,
        "note": "terminal only — not available in DevScope",
        "description": "Run diagnostics on the Claude installation.",
    },
    {
        "name": "/diff",
        "source": "builtin",
        "disabled": True,
        "note": "terminal only — not available in DevScope",
        "description": "Show git diff in the terminal.",
    },
    {
        "name": "/vim",
        "source": "builtin",
        "disabled": True,
        "note": "terminal only — not available in DevScope",
        "description": "Open a file in vim.",
    },
    {
        "name": "/ide",
        "source": "builtin",
        "disabled": True,
        "note": "terminal only — not available in DevScope",
        "description": "Launch IDE integration.",
    },
    {
        "name": "/theme",
        "source": "builtin",
        "disabled": True,
        "note": "terminal only — not available in DevScope",
        "description": "Change the terminal colour theme.",
    },
    {
        "name": "/config",
        "source": "builtin",
        "disabled": True,
        "note": "terminal only — not available in DevScope",
        "description": "Edit Claude configuration.",
    },
    {
        "name": "/rewind",
        "source": "builtin",
        "disabled": True,
        "note": "terminal only — not available in DevScope",
        "description": "Rewind the conversation to a previous point.",
    },
    {
        "name": "/teleport",
        "source": "builtin",
        "disabled": True,
        "note": "terminal only — not available in DevScope",
        "description": "Jump to a different context.",
    },
    {
        "name": "/agents",
        "source": "builtin",
        "disabled": True,
        "note": "Use the Subagent pill in the composer (claude --agent)",
        "description": "Switch Claude Code subagent — use the composer pill instead.",
    },
    {
        "name": "/mcp",
        "source": "builtin",
        "disabled": True,
        "note": "terminal only — not available in DevScope",
        "description": "Configure MCP servers.",
    },
    {
        "name": "/hooks",
        "source": "builtin",
        "disabled": True,
        "note": "terminal only — not available in DevScope",
        "description": "Manage event hooks.",
    },
    {
        "name": "/permissions",
        "source": "builtin",
        "disabled": True,
        "note": "terminal only — not available in DevScope",
        "description": "Manage tool permissions.",
    },
    {
        "name": "/skills",
        "source": "builtin",
        "disabled": True,
        "note": "terminal only — not available in DevScope",
        "description": "Browse available skills.",
    },
    {
        "name": "/init",
        "source": "builtin",
        "disabled": True,
        "note": "terminal only — not available in DevScope",
        "description": "Initialise a CLAUDE.md in the current directory.",
    },
    {
        "name": "/focus",
        "source": "builtin",
        "disabled": True,
        "note": "terminal only — not available in DevScope",
        "description": "Focus on a specific file or directory.",
    },
]

# Set of names for the interactive-only (disabled) stubs.
DISABLED_BUILTIN_NAMES: frozenset[str] = frozenset(
    c["name"] for c in _BUILTIN_COMMANDS if c.get("disabled")
)

# Commands still shown in consumer product mode; everything else is flagged
# advanced_only and hidden by the extension UI there (Pro mode shows all —
# the flag is data-only, the bridge itself never gates on it).
_CONSUMER_VISIBLE_BUILTINS: frozenset[str] = frozenset({"/interrupt", "/compact", "/new"})

for _cmd in _BUILTIN_COMMANDS:
    _cmd["advanced_only"] = _cmd["name"] not in _CONSUMER_VISIBLE_BUILTINS


def scan_commands(project_root: Path | None = None) -> list[dict]:
    """Return a list of command dicts from built-ins + project + user .claude dirs.

    Scans:
      <project_root>/.claude/commands/*.md
      <project_root>/.claude/skills/*/SKILL.md
      ~/.claude/commands/*.md

    Each entry: {"name": "/foo", "description": "...", "source": "project"|"user"|"builtin"}
    """
    if project_root is None:
        project_root = Path(session_store.DEFAULT_CWD)

    commands: list[dict] = [dict(c) for c in _BUILTIN_COMMANDS]
    seen: set[str] = {c["name"] for c in commands}

    scan_dirs = [
        (project_root / ".claude" / "commands", "project"),
        (project_root / ".claude" / "skills", "project"),
        (Path.home() / ".claude" / "commands", "user"),
    ]

    for base, source in scan_dirs:
        if not base.is_dir():
            continue
        if base.name == "skills":
            for skill_dir in sorted(base.iterdir()):
                if skill_dir.is_dir():
                    skill_file = skill_dir / "SKILL.md"
                    if skill_file.is_file():
                        _collect_command(commands, seen, skill_file, source)
        else:
            for md_file in sorted(base.glob("*.md")):
                _collect_command(commands, seen, md_file, source)

    return commands


def _collect_command(
    commands: list[dict],
    seen: set[str],
    path: Path,
    source: str,
) -> None:
    stem = path.stem if path.name != "SKILL.md" else path.parent.name
    name = f"/{stem}"
    if name in seen:
        return
    seen.add(name)
    description = _extract_description(path)
    commands.append({
        "name": name,
        "description": description,
        "source": source,
        # Discovered .md commands are dev workflows — hidden in consumer mode.
        "advanced_only": True,
    })


def _extract_description(path: Path) -> str:
    """Return the first useful description line from a .md file.

    Checks YAML frontmatter 'description:' key first, then falls back to the
    first non-empty non-heading line in the body.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""

    lines = text.splitlines()

    if lines and lines[0].strip() == "---":
        for line in lines[1:]:
            if line.strip() == "---":
                break
            if line.lower().startswith("description:"):
                return line.split(":", 1)[1].strip().strip('"').strip("'")

    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and not stripped.startswith("---"):
            return stripped[:160]
    return ""
