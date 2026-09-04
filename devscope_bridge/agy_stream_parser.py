"""Parse agy / Gemini-era stream-json or plain -p output."""

from __future__ import annotations

import re
from typing import Any

_RESUME_RE = re.compile(
    r"--conversation[= ]([0-9a-fA-F-]{8,})",
)
_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
)


def session_id_from_obj(obj: dict[str, Any]) -> str | None:
    for key in ("conversationId", "conversation_id", "session_id", "sessionId", "id"):
        val = obj.get(key)
        if isinstance(val, str) and _UUID_RE.fullmatch(val.strip()):
            return val.strip()
    for container_key in ("init", "step_update", "result"):
        nested = obj.get(container_key)
        if isinstance(nested, dict):
            found = session_id_from_obj(nested)
            if found:
                return found
    return None


def session_id_from_text(text: str) -> str | None:
    m = _RESUME_RE.search(text)
    if m:
        return m.group(1)
    m = _UUID_RE.search(text)
    return m.group(0) if m else None


def activities_from_obj(obj: dict[str, Any]) -> list[tuple[str, str, str | None, str | None]]:
    ev = str(obj.get("type") or obj.get("event") or "")
    tool = obj.get("tool") or obj.get("name") or obj.get("function")
    if ev in ("tool_start", "tool_call", "tool.start") and tool:
        return [(str(tool), str(tool), None, "running")]
    if ev in ("tool_end", "tool_result", "tool.end") and tool:
        return [(str(tool), str(tool), None, "done")]
    if ev == "step_update" and isinstance(obj.get("step_update"), dict):
        step = obj["step_update"]
        step_type = str(step.get("step_type") or "")
        if step_type and step_type not in ("agent_response", "user_input"):
            state = str(step.get("state") or "").upper()
            status = "running" if state == "ACTIVE" else "error" if state in ("ERROR", "FAILED") else "done"
            label = str(step.get("title") or step.get("name") or step_type)
            return [(label, step_type, None, status)]
    return []


def parse_line_to_delta(line: str, accum: str) -> tuple[str | None, str, str | None]:
    stripped = line.strip()
    if not stripped:
        return None, accum, None
    try:
        import json

        obj = json.loads(stripped)
    except ValueError:
        if stripped.startswith(("{", "[")):
            return None, accum, None
        return stripped, accum + ("" if not accum else "\n") + stripped, session_id_from_text(stripped)

    if not isinstance(obj, dict):
        return None, accum, None

    sid = session_id_from_obj(obj)
    ev = str(obj.get("type") or obj.get("event") or "")
    if ev == "step_update" and isinstance(obj.get("step_update"), dict):
        step = obj["step_update"]
        if step.get("step_type") != "agent_response":
            return None, accum, sid
        delta = step.get("text_delta")
        if not isinstance(delta, str) or not delta:
            return None, accum, sid
        return delta, accum + delta, sid
    if ev == "result" and isinstance(obj.get("result"), dict):
        response = obj["result"].get("response")
        if not isinstance(response, str) or not response:
            return None, accum, sid
        if response == accum:
            return None, accum, sid
        if accum and response.startswith(accum):
            delta = response[len(accum):]
            return (delta or None), response, sid
        return response, response, sid
    if ev in ("assistant", "message", "content", "text", "output"):
        text = obj.get("text") or obj.get("content") or obj.get("message")
        if isinstance(text, dict):
            text = text.get("text") or text.get("content")
        if not text:
            return None, accum, sid
        chunk = str(text)
        if accum and chunk.startswith(accum):
            delta = chunk[len(accum):]
            return (delta or None), chunk, sid
        return chunk, accum + chunk, sid
    if ev in ("text_delta", "delta"):
        t = obj.get("text") or obj.get("delta")
        if not t:
            return None, accum, sid
        return str(t), accum + str(t), sid
    return None, accum, sid
