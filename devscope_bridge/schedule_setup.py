"""Draft storage + dedicated chat session for deep schedule setup."""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any

from devscope_bridge import session_manager, session_store
from devscope_bridge.schedule_playbook import empty_playbook, merge_playbook, parse_playbook

logger = logging.getLogger(__name__)

_SETUP_DIR = Path.home() / ".dev-bridge" / "schedule_setups"
_ACTIVE_FILE = _SETUP_DIR / "active.json"

_SETUP_SYSTEM = (
    "You help the user configure a RECURRING scheduled browser automation for DevScope.\n\n"
    "Research the target site deeply using browser-control MCP (read-only during setup):\n"
    "  browser_list_tabs, browser_get_page_info, browser_navigate, browser_snapshot, "
    "browser_get_elements\n\n"
    "Build a durable Playbook: workflow steps, CSS selectors, checklist, notes.\n"
    "Do NOT submit forms, post publicly, send messages, purchase, or delete.\n\n"
    "Whenever the playbook improves, call schedule_setup_update(draft_id, patch).\n"
    "When the per-run instruction is clear, call schedule_setup_set_instruction(draft_id, instruction).\n"
    "Iterate with the user until they confirm the setup is complete."
)


def _save_active(draft: dict[str, Any]) -> None:
    _SETUP_DIR.mkdir(parents=True, exist_ok=True)
    _ACTIVE_FILE.write_text(json.dumps(draft, ensure_ascii=False, indent=2), "utf-8")


def load_active() -> dict[str, Any] | None:
    if not _ACTIVE_FILE.exists():
        return None
    try:
        data = json.loads(_ACTIVE_FILE.read_text("utf-8"))
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def get_draft(draft_id: str) -> dict[str, Any] | None:
    active = load_active()
    if active and active.get("id") == draft_id:
        return active
    path = _SETUP_DIR / f"{draft_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _persist_draft(draft: dict[str, Any]) -> dict[str, Any]:
    draft_id = draft["id"]
    _SETUP_DIR.mkdir(parents=True, exist_ok=True)
    path = _SETUP_DIR / f"{draft_id}.json"
    path.write_text(json.dumps(draft, ensure_ascii=False, indent=2), "utf-8")
    if draft.get("status") == "active":
        _save_active(draft)
    return draft


def clear_active() -> None:
    if _ACTIVE_FILE.exists():
        _ACTIVE_FILE.unlink()


def _session_name(draft_id: str) -> str:
    return f"sched-setup-{draft_id}"


def build_bootstrap_prompt(draft: dict[str, Any]) -> str:
    pb = parse_playbook(draft.get("playbook"))
    block = ""
    if pb.get("workflow") or pb.get("selectors"):
        block = f"\nCurrent playbook draft:\n{json.dumps(pb, ensure_ascii=False, indent=2)}\n"
    return (
        f"{_SETUP_SYSTEM}\n\n"
        f"Draft ID: {draft['id']}\n"
        f"Title: {draft.get('title', '')}\n"
        f"Goal: {draft.get('goal', '')}\n"
        f"Entry URL: {draft.get('entry_url', '')}\n"
        f"Domain: {draft.get('domain', 'browser')}\n"
        f"Runtime engine: {draft.get('agent', 'claude')}\n"
        f"{block}\n"
        "Start by confirming the entry URL is reachable in the bound browser tab, "
        "then map the page. Ask clarifying questions if the goal is ambiguous."
    )


async def start_setup(
    *,
    title: str,
    goal: str,
    entry_url: str,
    domain: str = "browser",
    agent: str = "claude",
    setup_mode: str = "inspect",
    instruction: str | None = None,
) -> dict[str, Any]:
    """Create draft + dedicated setup session. Returns draft dict."""
    if agent not in ("claude", "cursor"):
        agent = "claude"
    if setup_mode not in ("inspect", "plan", "act"):
        setup_mode = "inspect"

    draft_id = uuid.uuid4().hex[:8]
    session_name = _session_name(draft_id)
    draft: dict[str, Any] = {
        "id": draft_id,
        "session_name": session_name,
        "title": title.strip(),
        "goal": goal.strip(),
        "entry_url": entry_url.strip(),
        "domain": domain,
        "agent": agent,
        "setup_mode": setup_mode,
        "runtime_mode": "act",
        "playbook": empty_playbook(),
        "instruction": (instruction or "").strip() or None,
        "status": "active",
        "bootstrapped": False,
    }
    if entry_url.strip():
        draft["playbook"]["entry_urls"] = [entry_url.strip()]

    _persist_draft(draft)

    if session_store.get_session(session_name) is None:
        session_store.create_session_metadata(
            session_name,
            agent=agent,
            cwd=session_store.DEFAULT_CWD,
            mode=setup_mode,
            purpose="schedule_setup",
        )

    return draft


async def bootstrap_session(draft_id: str) -> dict[str, Any]:
    """Send first setup prompt once (deep-research kickoff)."""
    draft = get_draft(draft_id)
    if not draft:
        return {"ok": False, "error": "draft not found"}
    if draft.get("bootstrapped"):
        return {"ok": True, "draft": draft, "skipped": True}

    session_name = draft["session_name"]
    prompt = build_bootstrap_prompt(draft)
    await session_manager.run_prompt(
        session_name,
        prompt,
        mode=draft.get("setup_mode") or "inspect",
    )
    draft["bootstrapped"] = True
    _persist_draft(draft)
    return {"ok": True, "draft": draft, "session_name": session_name}


def update_playbook(draft_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    draft = get_draft(draft_id)
    if not draft:
        return None
    merged = merge_playbook(parse_playbook(draft.get("playbook")), patch)
    draft["playbook"] = merged
    return _persist_draft(draft)


def set_instruction(draft_id: str, instruction: str) -> dict[str, Any] | None:
    draft = get_draft(draft_id)
    if not draft:
        return None
    draft["instruction"] = instruction.strip() or None
    return _persist_draft(draft)


def complete_draft(draft_id: str) -> dict[str, Any] | None:
    draft = get_draft(draft_id)
    if not draft:
        return None
    draft["status"] = "completed"
    _persist_draft(draft)
    if load_active() and load_active().get("id") == draft_id:
        clear_active()
    return draft


def runtime_from_schedule_template(tmpl: dict[str, Any]) -> tuple[str, str]:
    agent = tmpl.get("agent") or "claude"
    if agent not in ("claude", "cursor"):
        agent = "claude"
    mode = tmpl.get("mode") or "act"
    if mode not in ("act", "plan", "inspect", "test"):
        mode = "act"
    return agent, mode


def runtime_for_task(task: dict[str, Any]) -> tuple[str, str]:
    from devscope_bridge import task_store

    sid = task.get("schedule_id")
    if not sid:
        return "claude", "act"
    sched = task_store.get_schedule(sid)
    if not sched:
        return "claude", "act"
    tmpl = sched.get("template")
    if not tmpl:
        try:
            tmpl = json.loads(sched.get("template_json") or "{}")
        except (json.JSONDecodeError, TypeError):
            tmpl = {}
    return runtime_from_schedule_template(tmpl if isinstance(tmpl, dict) else {})
