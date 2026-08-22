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

_SETUP_SYSTEM = (
    "You are setting up a new RECURRING task ('עובד') for DevScope, in a chat with the "
    "user. Speak natural Hebrew, like a colleague being onboarded — short messages, one "
    "topic at a time, no forms and no bullet interrogations.\n\n"
    "Find out conversationally:\n"
    "  1. WHAT the task does each run (the per-run instruction).\n"
    "  2. WHEN it runs — recurrence: {\"daily_at\": \"HH:MM\"} | {\"every_minutes\": N} | "
    "{\"weekly_at\": {\"day\": 0-6, \"time\": \"HH:MM\"}}.\n"
    "  3. WHERE it works (entry URL / site), if it touches the browser.\n"
    "  4. Which engine runs it: claude or cursor.\n"
    "  5. The autonomy policy — free text describing what the task may decide alone "
    "and what must wait for the user (money, publishing, deletion are ALWAYS asked).\n\n"
    "As facts land, keep the draft updated: schedule_setup_set_meta(draft_id, ...) for "
    "title/recurrence/agent/autonomy_policy/entry_url/goal, "
    "schedule_setup_set_instruction(draft_id, instruction) for the per-run instruction, "
    "and schedule_setup_update(draft_id, patch) for playbook knowledge.\n\n"
    "If a site is involved, research it with browser-control MCP (read-only during setup):\n"
    "  browser_list_tabs, browser_get_page_info, browser_navigate, browser_snapshot, "
    "browser_get_elements\n"
    "Build a durable Playbook: workflow steps, CSS selectors, checklist, notes.\n"
    "Do NOT submit forms, post publicly, send messages, purchase, or delete.\n\n"
    "When everything is in place, summarize the setup in Hebrew and ask for explicit "
    "confirmation. ONLY after the user confirms, call schedule_commit(draft_id)."
)


def get_draft(draft_id: str) -> dict[str, Any] | None:
    path = _SETUP_DIR / f"{draft_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def find_draft_by_session(session_name: str) -> dict[str, Any] | None:
    if not _SETUP_DIR.is_dir():
        return None
    for path in _SETUP_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text("utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(data, dict) and data.get("session_name") == session_name:
            return data
    return None


def _persist_draft(draft: dict[str, Any]) -> dict[str, Any]:
    draft_id = draft["id"]
    _SETUP_DIR.mkdir(parents=True, exist_ok=True)
    path = _SETUP_DIR / f"{draft_id}.json"
    path.write_text(json.dumps(draft, ensure_ascii=False, indent=2), "utf-8")
    return draft


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
    title: str = "משימה חדשה",
    goal: str = "",
    entry_url: str = "",
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
        "recurrence": {},
        "autonomy_policy": None,
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
    return _persist_draft(draft)


_META_FIELDS = ("title", "recurrence", "agent", "autonomy_policy", "entry_url", "goal")


def set_meta(draft_id: str, meta: dict[str, Any]) -> dict[str, Any] | None:
    draft = get_draft(draft_id)
    if not draft:
        return None
    for key in _META_FIELDS:
        if key in meta and meta[key] is not None:
            draft[key] = meta[key]
    if meta.get("entry_url"):
        pb = parse_playbook(draft.get("playbook"))
        if meta["entry_url"] not in (pb.get("entry_urls") or []):
            draft["playbook"] = merge_playbook(pb, {"entry_urls": [meta["entry_url"]]})
    return _persist_draft(draft)


def commit_draft(draft_id: str) -> tuple[dict[str, Any] | None, str | None]:
    """Create the schedule from a completed draft. Returns (schedule, error)."""
    from datetime import datetime

    from devscope_bridge import task_store
    from devscope_bridge.orchestrator_core import _next_run_at

    draft = get_draft(draft_id)
    if not draft:
        return None, "draft not found"
    instruction = (draft.get("instruction") or draft.get("goal") or "").strip()
    if not instruction:
        return None, "draft needs an instruction or goal before commit"
    recurrence = draft.get("recurrence") or {}
    if not recurrence:
        return None, "draft needs a recurrence before commit"

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    template = {
        "title": draft.get("title") or "משימה חדשה",
        "kind": "worker_unit",
        "detail": draft.get("goal") or None,
        "domain": draft.get("domain") or "browser",
        "instruction": instruction,
        "autonomy": "guarded",
        "autonomy_policy": draft.get("autonomy_policy"),
        "agent": draft.get("agent") or "claude",
        "mode": draft.get("runtime_mode") or "act",
        "recurrence": recurrence,
    }
    sid = task_store.add_schedule(
        title=template["title"],
        template={k: v for k, v in template.items() if v is not None},
        playbook=parse_playbook(draft.get("playbook")),
        next_run_at=_next_run_at(recurrence, now),
    )
    draft["status"] = "committed"
    draft["schedule_id"] = sid
    _persist_draft(draft)
    return task_store.get_schedule(sid), None


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
