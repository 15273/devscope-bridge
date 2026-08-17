"""Pure 'waiting on you' computation. No I/O.

A chat is open (the user forgot to reply) when its last message is not from the
user and more than ``threshold_s`` seconds have elapsed, and the chat is in
scope and not muted.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence


def compute(chats: Sequence[Mapping[str, Any]], *, now: int,
            threshold_s: int) -> list[dict]:
    out: list[dict] = []
    for c in chats:
        if not c["in_scope"] or c["muted"]:
            continue
        if c["last_msg_from_me"]:
            continue
        # Skip chats with an unknown last-message time (not yet loaded in
        # WhatsApp Web) — otherwise ts=0 reads as "decades ago" and floods the
        # queue with false nudges.
        if c["last_msg_ts"] <= 0:
            continue
        if now - c["last_msg_ts"] < threshold_s:
            continue
        out.append({"chat_id": c["id"], "since_ts": c["last_msg_ts"]})
    out.sort(key=lambda n: n["since_ts"])  # oldest first
    return out
