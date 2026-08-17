"""
agents_scanner.py — Scan .claude/agents/*.md for Claude Code subagent definitions.

Each agent file uses YAML frontmatter with at least ``name`` and ``description``.
The ``name`` slug is passed to ``claude --agent <name>`` when a session selects it.
"""

from __future__ import annotations

import re
from pathlib import Path

from devscope_bridge import session_store

_FRONTMATTER_RE = re.compile(
    r"^---\s*\n(.*?)\n---",
    re.DOTALL,
)


def scan_agents(project_root: Path | None = None) -> list[dict]:
    """Return agent dicts from ``<project>/.claude/agents/*.md``.

    Each entry: ``{"name": "ht-backend-engineer", "description": "...", "model": "sonnet"|None}``
    """
    if project_root is None:
        project_root = Path(session_store.DEFAULT_CWD)

    agents_dir = project_root / ".claude" / "agents"
    if not agents_dir.is_dir():
        return []

    seen: set[str] = set()
    agents: list[dict] = []
    for md_file in sorted(agents_dir.glob("*.md")):
        meta = _parse_frontmatter(md_file)
        slug = meta.get("name") or _slug_from_stem(md_file.stem)
        if slug in seen:
            continue
        seen.add(slug)
        desc = meta.get("description") or md_file.stem.replace("-", " ").replace("_", " ")
        agents.append({
            "name": slug,
            "description": desc[:240],
            "model": meta.get("model"),
            "source": "project",
            "file": md_file.name,
        })
    return agents


def _slug_from_stem(stem: str) -> str:
    return stem.lower().replace("_", "-")


def _parse_frontmatter(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}
    meta: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        meta[key.strip().lower()] = val.strip().strip('"').strip("'")
    return meta
