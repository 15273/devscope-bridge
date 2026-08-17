"""
schedule_playbook.py — Persistent memory for recurring scheduled tasks.

Stores reusable page knowledge (selectors, workflow steps, URLs) so each run
does not rediscover DOM structure from scratch.
"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any


def empty_playbook() -> dict[str, Any]:
    return {
        "version": 1,
        "site": "",
        "entry_urls": [],
        "workflow": [],
        "selectors": {},
        "fields": {},
        "notes": "",
        "checklist": [],
        "last_success_at": None,
        "learned_from_runs": 0,
    }


def parse_playbook(raw: str | dict | None) -> dict[str, Any]:
    if raw is None or raw == "":
        return empty_playbook()
    if isinstance(raw, dict):
        data = deepcopy(raw)
    else:
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return empty_playbook()
    if not isinstance(data, dict):
        return empty_playbook()
    base = empty_playbook()
    base.update(data)
    return base


def merge_playbook(existing: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge a patch into an existing playbook. Lists extend; dicts merge."""
    out = parse_playbook(existing)
    for key, val in patch.items():
        if val is None:
            continue
        if key in ("selectors", "fields") and isinstance(val, dict):
            current = out.get(key) if isinstance(out.get(key), dict) else {}
            current.update(val)
            out[key] = current
        elif key in ("entry_urls", "workflow", "checklist") and isinstance(val, list):
            seen = set(out.get(key) or [])
            merged = list(out.get(key) or [])
            for item in val:
                if item and item not in seen:
                    merged.append(item)
                    seen.add(item)
            out[key] = merged
        else:
            out[key] = val
    if patch:
        out["learned_from_runs"] = int(out.get("learned_from_runs") or 0) + 1
    return out


def format_playbook_block(playbook: dict[str, Any]) -> str:
    """Human-readable block injected into worker instructions."""
    pb = parse_playbook(playbook)
    if not any([pb.get("site"), pb.get("entry_urls"), pb.get("workflow"),
                pb.get("selectors"), pb.get("notes"), pb.get("checklist")]):
        return ""

    lines = [
        "## Playbook (שמור — אל תגלה מחדש)",
        "Use the saved knowledge below. Only explore the DOM when a selector fails.",
        "After a successful run, call schedule_playbook_update() with any improved selectors.",
        "",
    ]
    if pb.get("site"):
        lines.append(f"Site: {pb['site']}")
    if pb.get("entry_urls"):
        lines.append("Entry URLs:")
        lines.extend(f"  - {u}" for u in pb["entry_urls"])
    if pb.get("workflow"):
        lines.append("Workflow:")
        lines.extend(f"  {i + 1}. {step}" for i, step in enumerate(pb["workflow"]))
    if pb.get("checklist"):
        lines.append("Pre-flight:")
        lines.extend(f"  - {c}" for c in pb["checklist"])
    if pb.get("selectors"):
        lines.append("Selectors:")
        for name, sel in pb["selectors"].items():
            if isinstance(sel, list):
                lines.append(f"  {name}: {' | '.join(sel)}")
            else:
                lines.append(f"  {name}: {sel}")
    if pb.get("fields"):
        lines.append("Fields:")
        for name, hint in pb["fields"].items():
            lines.append(f"  {name}: {hint}")
    if pb.get("notes"):
        lines.append(f"Notes:\n{pb['notes']}")
    if pb.get("last_success_at"):
        lines.append(f"Last success: {pb['last_success_at']}")
    return "\n".join(lines)


def build_scheduled_instruction(base_instruction: str | None, playbook: dict[str, Any]) -> str:
    block = format_playbook_block(playbook)
    parts = [p for p in (base_instruction or "", block) if p.strip()]
    return "\n\n".join(parts)
