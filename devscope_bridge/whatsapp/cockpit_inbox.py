"""Inbox-wide WhatsApp queries: unread DMs/groups with filter detection."""

from __future__ import annotations

import re
from typing import Any

from devscope_bridge.whatsapp import cockpit_sync, whatsapp_engine

# ── Query / filter detection ─────────────────────────────────────────────────

_INBOX_HINTS = (
    "הודעות חדשות", "מה חדש", "יש חדש", "unread", "לא נקרא",
    "מי כתב", "מי שלח", "מה מחכה", "מה פתוח", "סיכום הודעות",
    "new messages", "what's new", "whats new",
)

_DMS_ONLY_HINTS = (
    "לא בקבוצות", "לא קבוצות", "בלי קבוצות", "ללא קבוצות",
    "צ'אטים פרטיים", "צאטים פרטיים", "פרטיים בלבד", "רק פרטיים",
    "direct message", "dms only", "private chat", "private chats",
    "not groups", "no groups",
)

_GROUPS_ONLY_HINTS = (
    "רק קבוצות", "קבוצות בלבד", "בקבוצות בלבד", "groups only", "only groups",
)

_REFINEMENT_HINTS = _DMS_ONLY_HINTS + _GROUPS_ONLY_HINTS + (
    "רק ", "בלי ", "לא ", "only ", "just ",
)


def _normalize(text: str) -> str:
    return (text or "").strip().lower()


def _contains_any(text: str, hints: tuple[str, ...]) -> bool:
    t = _normalize(text)
    return any(h.lower() in t for h in hints)


def is_inbox_query(question: str, history: list[dict[str, str]] | None = None) -> bool:
    """True when the user wants a cross-chat inbox view, not one thread."""
    if _contains_any(question, _INBOX_HINTS):
        return True
    if not history:
        return False
    for turn in reversed(history):
        if turn.get("role") == "user" and _contains_any(turn.get("content", ""), _INBOX_HINTS):
            return True
    return False


def is_refinement(question: str) -> bool:
    q = question.strip()
    if len(q) > 80:
        return False
    return _contains_any(q, _REFINEMENT_HINTS)


def effective_question(question: str, history: list[dict[str, str]] | None) -> str:
    """Merge short follow-ups ('לא בקבוצות') with the prior user question."""
    if not history or not is_refinement(question):
        return question
    for turn in reversed(history):
        if turn.get("role") == "user":
            prev = (turn.get("content") or "").strip()
            if prev and prev != question.strip():
                return f"{prev} ({question.strip()})"
            break
    return question


def parse_filters(
    question: str,
    history: list[dict[str, str]] | None = None,
) -> dict[str, bool]:
    """Detect DM-only / group-only from current question + recent user turns."""
    parts = [question]
    if history:
        for turn in reversed(history[-6:]):
            if turn.get("role") == "user":
                parts.append(turn.get("content", ""))
    blob = " ".join(parts)
    dms_only = _contains_any(blob, _DMS_ONLY_HINTS)
    groups_only = _contains_any(blob, _GROUPS_ONLY_HINTS)
    if dms_only and groups_only:
        groups_only = False
    return {"dms_only": dms_only, "groups_only": groups_only}


def should_use_inbox(
    question: str,
    chat_id: str | None,
    history: list[dict[str, str]] | None,
    *,
    dms_only: bool = False,
    groups_only: bool = False,
) -> bool:
    """Inbox mode overrides single-chat scope when the intent is cross-chat."""
    if dms_only or groups_only:
        return True
    if is_inbox_query(question, history):
        return True
    if is_refinement(question) and history and is_inbox_query("", history):
        return True
    if not chat_id and is_inbox_query(question, None):
        return True
    return False


# ── Live fetch + formatting ──────────────────────────────────────────────────

def _filter_chats(
    chats: list[dict[str, Any]],
    *,
    dms_only: bool,
    groups_only: bool,
) -> list[dict[str, Any]]:
    if dms_only:
        return [c for c in chats if not c.get("isGroup")]
    if groups_only:
        return [c for c in chats if c.get("isGroup")]
    return chats


def format_inbox_block(
    chats: list[dict[str, Any]],
    *,
    dms_only: bool,
    groups_only: bool,
    total_unread_before_filter: int,
) -> str:
    if dms_only:
        scope = "private chats (DMs) only — NO groups"
    elif groups_only:
        scope = "groups only — NO private chats"
    else:
        scope = "all chats (DMs and groups)"

    lines = [
        f"WhatsApp unread inbox — {scope}",
        f"Showing {len(chats)} unread chat(s) (of {total_unread_before_filter} total unread).",
        "",
    ]
    if not chats:
        lines.append("No unread chats match this filter.")
        return "\n".join(lines)

    for c in chats:
        kind = "group" if c.get("isGroup") else "dm"
        unread = int(c.get("unreadCount") or 0)
        preview = (c.get("lastMessage") or {}).get("preview") or ""
        preview = re.sub(r"\s+", " ", preview).strip()[:100]
        lines.append(
            f"- [{kind}] {c.get('name') or c.get('id')} "
            f"({unread} unread): {preview or '(no preview)'}"
        )
    return "\n".join(lines)


async def fetch_unread_inbox(
    session: str | None,
    *,
    dms_only: bool = False,
    groups_only: bool = False,
    limit: int = 40,
) -> tuple[list[dict[str, Any]], int, str | None]:
    """Return (filtered chats, total unread before filter, error)."""
    session = await cockpit_sync.pick_wa_session(session)
    if not session:
        return [], 0, "אין DevScope session מחובר"

    res = await whatsapp_engine.list_chats(filter="unread", limit=100, session=session)
    if not res.get("ok"):
        return [], 0, str(res.get("error") or "list_chats failed")

    all_unread = list(res.get("data") or [])
    filtered = _filter_chats(all_unread, dms_only=dms_only, groups_only=groups_only)
    return filtered[:limit], len(all_unread), None
