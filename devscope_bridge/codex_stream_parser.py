"""Parse `codex exec --json` JSONL into text deltas + tool activity."""

from __future__ import annotations

from typing import Any


def session_id_from_obj(obj: dict[str, Any]) -> str | None:
    for key in ("thread_id", "threadId", "session_id"):
        val = obj.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    thread = obj.get("thread")
    if isinstance(thread, dict):
        tid = thread.get("id") or thread.get("thread_id")
        if isinstance(tid, str) and tid.strip():
            return tid.strip()
    return None


def _item_text(item: dict[str, Any]) -> str:
    for key in ("text", "message", "content"):
        val = item.get(key)
        if isinstance(val, str) and val:
            return val
    return ""


def _item_type(item: dict[str, Any]) -> str:
    return str(item.get("type") or item.get("item_type") or "")


def activities_from_obj(obj: dict[str, Any]) -> list[tuple[str, str, str | None, str | None]]:
    ev = str(obj.get("type") or "")
    item = obj.get("item") if isinstance(obj.get("item"), dict) else None
    if item is None and ev.startswith("item/"):
        item = obj
    if not isinstance(item, dict):
        return []
    kind = _item_type(item)
    if kind in ("command_execution", "commandExecution", "mcp_tool_call", "mcpToolCall", "file_change", "fileChange"):
        tool = kind.replace("_", "")
        label = str(item.get("command") or item.get("name") or kind)
        detail = str(item.get("cwd") or item.get("detail") or "") or None
        if ev in ("item.started", "item/started"):
            return [(label, tool, detail, "running")]
        if ev in ("item.completed", "item/completed"):
            status = "error" if item.get("status") in ("failed", "declined", "error") else "done"
            return [(label, tool, detail, status)]
    return []


def parse_line_to_delta(line: str, accum: str) -> tuple[str | None, str, str | None]:
    stripped = line.strip()
    if not stripped:
        return None, accum, None
    try:
        obj = json_loads(stripped)
    except ValueError:
        if stripped.startswith(("{", "[")):
            return None, accum, None
        return stripped, accum + stripped, None

    if not isinstance(obj, dict):
        return None, accum, None

    sid = session_id_from_obj(obj)
    ev = str(obj.get("type") or obj.get("method") or "")

    if ev in ("thread.started", "thread/started"):
        return None, accum, sid

    if ev in ("item.completed", "item/completed"):
        item = obj.get("item") if isinstance(obj.get("item"), dict) else {}
        kind = _item_type(item)
        if kind in ("agent_message", "agentMessage", "message"):
            text = _item_text(item)
            if not text:
                return None, accum, sid
            if accum and text.startswith(accum):
                delta = text[len(accum):]
                return (delta or None), text, sid
            if text == accum:
                return None, accum, sid
            return text if not accum else text, (accum + text if text != accum else accum), sid
        return None, accum, sid

    if ev in ("item.agent_message.delta", "item/agentMessage/delta"):
        delta = obj.get("delta") or obj.get("text")
        if not delta:
            return None, accum, sid
        text = str(delta)
        return text, accum + text, sid

    if ev in ("error", "turn.failed", "turn/failed"):
        err = obj.get("error") or obj.get("message") or obj.get("detail")
        if isinstance(err, dict):
            err = err.get("message") or err.get("detail")
        if err:
            return None, accum, sid
        return None, accum, sid

    return None, accum, sid


def json_loads(raw: str) -> Any:
    import json

    return json.loads(raw)
