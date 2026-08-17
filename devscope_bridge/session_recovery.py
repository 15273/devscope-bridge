"""Transcript recovery preambles and stream-json stdin encoding."""

from __future__ import annotations

import json

from devscope_bridge import session_store

# Joins a compact/recovery preamble to the user's message. Without the explicit
# boundary the model reads the summary's "continue from here" and resumes the
# OLD task, ignoring the new message buried below a bare "---".
_PREAMBLE_USER_MSG_SEPARATOR = (
    "\n\n--- END OF BACKGROUND ---\n"
    "The message below is the user's CURRENT request — respond to it. "
    "Everything above is background context only; do not resume prior tasks "
    "unless the message below asks for that.\n\n"
)


def _encode_user_message(text: str, images: list[dict] | None = None) -> bytes:
    """Encode a user turn as a newline-delimited JSON stdin line for stream-json mode.

    `images` are Claude image content blocks (from extract_image_blocks). They
    are placed before the text block, which is what Anthropic recommends for
    best results when an image accompanies a prompt.
    """
    content: list[dict] = list(images or [])
    content.append({"type": "text", "text": text})
    payload = {
        "type": "user",
        "message": {"role": "user", "content": content},
    }
    return (json.dumps(payload) + "\n").encode("utf-8")



def _message_text(entry: dict) -> str:
    """Extract plain text from a transcript message entry (string or block list)."""
    content = entry.get("message", {}).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
        return " ".join(p for p in parts if p)
    return ""


_SHORT_CONTINUATION_MAX = 80


def _cursor_needs_recovery_preamble(prompt: str, prior_session_id: str | None) -> bool:
    """Inject bridge transcript summary when Cursor may lack thread context."""
    if not prior_session_id:
        return True
    return len(prompt.strip()) <= _SHORT_CONTINUATION_MAX


def build_recovery_preamble(name: str) -> str | None:
    """Rebuild a compact context summary from stored transcript turns.

    Used after a forced respawn (no --resume) or for Cursor when chatId is missing.
    Returns None when there is no transcript or nothing extractable.
    """
    turns = session_store.read_transcript_turns(name, limit=24)
    if not turns:
        return None

    recent_users = [t["text"] for t in turns if t["role"] == "user"][-3:]
    recent_assistants = [t["text"] for t in turns if t["role"] == "assistant"][-2:]
    if not recent_users and not recent_assistants:
        return None

    lines = [
        "[Bridge context recovery] The agent process restarted without in-memory history.",
        "Continue the SAME thread — do not ask what task the user meant unless truly ambiguous.",
        "",
        "Recent user messages:",
    ]
    for text in recent_users:
        lines.append(f"- {text[:500]}")
    lines.append("")
    lines.append("Recent assistant progress:")
    for text in recent_assistants:
        lines.append(f"- {text[:800]}")
    lines.append("")
    lines.append(
        "Short replies like \"done\", \"בוצע\", or \"try now\" refer to the ongoing work above."
    )
    return "\n".join(lines)

