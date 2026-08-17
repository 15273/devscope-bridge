"""cockpit_assistant.py — scoped Q&A and inbox-wide WhatsApp assistant."""

from __future__ import annotations

from typing import Any

from devscope_bridge.whatsapp import cockpit_agent

_SYSTEM_PROMPT = (
    "You are the user's personal WhatsApp assistant. Answer concisely in the SAME "
    "language as the user's question (default Hebrew). You may summarize what is "
    "going on, surface what needs a reply, and recommend what to say. When you "
    "suggest a reply, write it in the language of the conversation and wrap it on "
    "its own line prefixed with 'הצעה לתשובה: '. Never claim you sent anything — "
    "sending always requires the user's explicit confirmation in the app."
)

_INBOX_EXTRA = (
    "\n\nINBOX MODE: You receive a factual list of unread chats (DMs and/or groups). "
    "Use ONLY that list — do not invent chats or messages. If the user asked for "
    "private chats only, do NOT mention groups at all. If they asked for groups only, "
    "do NOT mention DMs. Prioritize what likely needs a personal reply. "
    "If the list is empty, say so clearly."
)

_SINGLE_CHAT_EXTRA = (
    "\n\nSINGLE-CHAT MODE: You are given one conversation thread. "
    "Do not discuss other chats unless the user explicitly asks."
)


def _format_history(history: list[dict[str, str]] | None, limit: int = 6) -> str:
    if not history:
        return ""
    lines = ["Recent assistant conversation (for follow-up context):"]
    for turn in history[-limit:]:
        role = turn.get("role", "user")
        label = "User" if role == "user" else "Assistant"
        content = (turn.get("content") or "").strip()
        if content:
            lines.append(f"{label}: {content}")
    lines.append("")
    return "\n".join(lines)


def _build_single_chat_prompt(
    chat_name: str,
    messages: list[dict[str, Any]],
    question: str,
    history: list[dict[str, str]] | None,
) -> str:
    lines = [
        f"{'me' if m.get('from_me') else 'them'}: {m.get('text', '')}"
        for m in messages if m.get("text")
    ]
    thread = "\n".join(lines) if lines else "(no messages stored yet — use wa_get_messages if available)"
    parts = [_format_history(history), f"Chat: {chat_name}", f"Recent conversation (oldest first):\n{thread}", f"Question: {question}"]
    return "\n".join(p for p in parts if p.strip())


def _build_inbox_prompt(
    inbox_block: str,
    question: str,
    history: list[dict[str, str]] | None,
) -> str:
    parts = [
        _format_history(history),
        inbox_block,
        f"Question: {question}",
    ]
    return "\n\n".join(p for p in parts if p.strip())


async def ask(
    chat_name: str,
    messages: list[dict[str, Any]],
    question: str,
    *,
    history: list[dict[str, str]] | None = None,
    agent: str = "cursor",
    model: str | None = None,
    mode: str | None = "act",
    session_name: str | None = None,
) -> str:
    """Answer about one chat thread."""
    prompt = _build_single_chat_prompt(chat_name, messages, question, history)
    sys = _SYSTEM_PROMPT + _SINGLE_CHAT_EXTRA
    return await cockpit_agent.run(
        sys, prompt, agent=agent, model=model, mode=mode, session_name=session_name,
    )


async def ask_inbox(
    question: str,
    inbox_block: str,
    *,
    history: list[dict[str, str]] | None = None,
    agent: str = "cursor",
    model: str | None = None,
    mode: str | None = "act",
    session_name: str | None = None,
) -> str:
    """Answer about unread chats across the inbox."""
    prompt = _build_inbox_prompt(inbox_block, question, history)
    sys = _SYSTEM_PROMPT + _INBOX_EXTRA
    return await cockpit_agent.run(
        sys, prompt, agent=agent, model=model, mode=mode, session_name=session_name,
    )
