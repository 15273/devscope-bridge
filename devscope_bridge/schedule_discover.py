"""One-shot Claude + browser MCP to draft a schedule playbook from a live page."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any
from urllib.parse import urlparse

from devscope_bridge import browser_relay, session_manager, session_store
from devscope_bridge.schedule_playbook import parse_playbook

logger = logging.getLogger(__name__)

_DISCOVER_SYSTEM = (
    "You map websites for recurring browser automation stored as a Playbook.\n\n"
    "Use browser-control MCP on the user's DevScope-bound Chrome tab:\n"
    "  1. browser_list_tabs / browser_get_page_info — confirm context\n"
    "  2. browser_navigate — open the entry URL if needed\n"
    "  3. browser_snapshot + browser_get_elements — stable CSS selectors\n\n"
    "READ-ONLY exploration: do NOT submit forms, send messages, post publicly, "
    "purchase, or delete anything.\n\n"
    "Return ONLY one JSON object (no markdown fences, no commentary) with:\n"
    '  {"playbook": {"site","entry_urls","workflow","selectors","checklist","notes"}, '
    '"instruction": "concise instruction for each scheduled run"}\n'
    "workflow = ordered human-readable steps; selectors = logical name → CSS selector."
)

_TIMEOUT_S = 180.0


def _build_args(system_prompt: str) -> list[str]:
    return [
        "claude", "--print",
        "--input-format", "stream-json",
        "--output-format", "stream-json",
        "--include-partial-messages", "--verbose",
        "--permission-mode", "bypassPermissions",
        "--disallowed-tools", "AskUserQuestion",
        "--append-system-prompt", system_prompt,
    ]


def _encode_user_message(text: str) -> bytes:
    payload = {
        "type": "user",
        "message": {"role": "user", "content": [{"type": "text", "text": text}]},
    }
    return (json.dumps(payload) + "\n").encode("utf-8")


async def _collect_output(proc: asyncio.subprocess.Process) -> str:
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
        if event.get("type") == "stream_event":
            delta = event.get("event", {}).get("delta", {})
            if delta.get("type") == "text_delta":
                text = delta.get("text", "")
                if text:
                    chunks.append(text)
        elif event.get("type") == "result":
            break
    return "".join(chunks)


def extract_json_object(text: str) -> dict[str, Any] | None:
    """Best-effort JSON extraction from Claude free-form output."""
    raw = text.strip()
    if not raw:
        return None
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except json.JSONDecodeError:
            pass
    start, end = raw.find("{"), raw.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            pass
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _site_from_url(url: str) -> str:
    try:
        host = urlparse(url).netloc or ""
        return host.removeprefix("www.")
    except Exception:  # noqa: BLE001
        return ""


async def pick_browser_session(preferred: str | None) -> str | None:
    if preferred and preferred in browser_relay.candidate_sessions():
        return preferred
    return browser_relay.first_active_session()


async def discover_playbook(
    *,
    entry_url: str,
    goal: str,
    session_name: str | None = None,
    domain: str = "browser",
    agent: str = "claude",
    timeout_s: float = _TIMEOUT_S,
) -> dict[str, Any]:
    """Run Claude or Cursor browser mapping. Returns {ok, playbook, instruction, error, session}."""
    from devscope_bridge.whatsapp.cockpit_agent import run as run_agent

    session = await pick_browser_session(session_name)
    if not session:
        return {
            "ok": False,
            "error": "אין DevScope session מחובר — פתח sidepanel וחבר session",
            "session": None,
        }

    user_text = (
        f"Entry URL: {entry_url.strip()}\n"
        f"Domain: {domain}\n"
        f"Recurring task goal:\n{goal.strip()}\n\n"
        "Map the site and return ONLY the JSON object described in your instructions."
    )

    try:
        raw = await run_agent(
            _DISCOVER_SYSTEM,
            user_text,
            agent=agent if agent in ("claude", "cursor") else "claude",
            mode="inspect",
            session_name=session,
            timeout_s=timeout_s,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("schedule_discover failed: %s", exc)
        return {"ok": False, "error": str(exc), "session": session}

    if not raw.strip():
        agent_label = "Cursor" if agent == "cursor" else "Claude"
        return {
            "ok": False,
            "error": f"{agent_label} לא החזיר תשובה — נסה שוב או השתמש בצ'אט הגדרה",
            "session": session,
        }

    parsed = extract_json_object(raw)
    if not parsed:
        return {
            "ok": False,
            "error": "לא התקבל JSON תקין — נסה שוב, צ'אט הגדרה, או מלא playbook ידנית",
            "session": session,
            "raw_preview": raw[:500] if raw else "",
        }

    pb_raw = parsed.get("playbook") if isinstance(parsed.get("playbook"), dict) else {}
    playbook = parse_playbook(pb_raw)
    if entry_url.strip() and not playbook.get("entry_urls"):
        playbook["entry_urls"] = [entry_url.strip()]
    if not playbook.get("site"):
        playbook["site"] = _site_from_url(entry_url)

    instruction = parsed.get("instruction")
    if isinstance(instruction, str):
        instruction = instruction.strip() or None
    else:
        instruction = None

    return {
        "ok": True,
        "playbook": playbook,
        "instruction": instruction,
        "session": session,
    }
