"""Parse Grok headless NDJSON into text, thinking, and tool activity.

Supports both `--output-format streaming-json` (ACP `type` tags) and
`streaming-messages-json` (Claude-compatible stream_event / assistant / user).
"""

from __future__ import annotations

import json
from typing import Any

# label, tool, detail, status, call_id
Activity = tuple[str, str | None, str | None, str | None, str | None]


def session_id_from_obj(obj: dict[str, Any]) -> str | None:
    for key in ("sessionId", "session_id"):
        val = obj.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    msg = obj.get("message")
    if isinstance(msg, dict):
        sid = msg.get("session_id")
        if isinstance(sid, str) and sid.strip():
            return sid.strip()
    return None


def _short_tool(name: str) -> str:
    if name.startswith("mcp__browser-control__"):
        name = name.split("__")[-1]
    if name.startswith("browser_"):
        return name.removeprefix("browser_").replace("_", " ")
    return name


def _detail_from_input(raw: object) -> str | None:
    if not isinstance(raw, dict):
        return None
    for key in ("path", "command", "query", "url", "selector", "pattern", "file_path"):
        val = raw.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()[:240]
    return None


def thoughts_from_obj(obj: dict[str, Any]) -> str | None:
    ev = str(obj.get("type") or "")
    if ev == "thought":
        text = str(obj.get("data") or obj.get("text") or "")
        return text or None
    if ev == "stream_event":
        inner = obj.get("event") if isinstance(obj.get("event"), dict) else {}
        delta = inner.get("delta") if isinstance(inner.get("delta"), dict) else {}
        if delta.get("type") == "thinking_delta":
            text = str(delta.get("thinking") or delta.get("text") or "")
            return text or None
    if ev == "assistant":
        content = (obj.get("message") or {}).get("content") or []
        bits: list[str] = []
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "thinking":
                    t = str(block.get("thinking") or block.get("text") or "")
                    if t:
                        bits.append(t)
        return "".join(bits) or None
    return None


def activities_from_obj(obj: dict[str, Any]) -> list[Activity]:
    ev = str(obj.get("type") or "")
    if ev == "tool_call":
        call_id = str(obj.get("toolCallId") or obj.get("id") or "").strip() or None
        tool = str(obj.get("toolName") or obj.get("kind") or "tool")
        title = str(obj.get("title") or _short_tool(tool))
        detail = _detail_from_input(obj.get("rawInput"))
        status = str(obj.get("status") or "in_progress")
        running = status in ("in_progress", "pending", "running", "")
        return [(title, tool, detail, "running" if running else "done", call_id)]
    if ev == "tool_call_update":
        call_id = str(obj.get("toolCallId") or obj.get("id") or "").strip() or None
        tool = str(obj.get("toolName") or obj.get("kind") or "tool")
        title = str(obj.get("title") or tool)
        detail = _detail_from_input(obj.get("rawOutput")) or _detail_from_input(obj.get("rawInput"))
        status = str(obj.get("status") or "")
        done = "error" if status in ("failed", "error", "cancelled") else "done"
        return [(title, tool, detail, done, call_id)]
    if ev == "stream_event":
        inner = obj.get("event") if isinstance(obj.get("event"), dict) else {}
        if inner.get("type") == "content_block_start":
            block = inner.get("content_block") if isinstance(inner.get("content_block"), dict) else {}
            if block.get("type") == "tool_use":
                call_id = str(block.get("id") or "").strip() or None
                tool = str(block.get("name") or "tool")
                detail = _detail_from_input(block.get("input"))
                return [(tool, tool, detail, "running", call_id)]
        return []
    if ev == "assistant":
        content = (obj.get("message") or {}).get("content") or []
        out: list[Activity] = []
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                call_id = str(block.get("id") or "").strip() or None
                tool = str(block.get("name") or "tool")
                detail = _detail_from_input(block.get("input"))
                out.append((_short_tool(tool), tool, detail, "running", call_id))
        return out
    if ev == "user":
        content = (obj.get("message") or {}).get("content") or []
        out = []
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                call_id = str(block.get("tool_use_id") or "").strip() or None
                is_err = bool(block.get("is_error"))
                raw = block.get("content")
                detail = raw if isinstance(raw, str) else None
                if detail and len(detail) > 240:
                    detail = detail[:240]
                out.append(("tool", "tool", detail, "error" if is_err else "done", call_id))
        return out
    return []


def parse_line_to_delta(line: str, accum: str) -> tuple[str | None, str, str | None]:
    stripped = line.strip()
    if not stripped:
        return None, accum, None
    try:
        obj = json.loads(stripped)
    except ValueError:
        if stripped.startswith(("{", "[")):
            return None, accum, None
        return stripped, accum + stripped, None
    if not isinstance(obj, dict):
        return None, accum, None
    sid = session_id_from_obj(obj)
    ev = str(obj.get("type") or "")
    if ev == "text":
        text = str(obj.get("data") or obj.get("text") or "")
        if not text:
            return None, accum, sid
        return text, accum + text, sid
    if ev == "stream_event":
        inner = obj.get("event") if isinstance(obj.get("event"), dict) else {}
        delta = inner.get("delta") if isinstance(inner.get("delta"), dict) else {}
        if delta.get("type") == "text_delta":
            text = str(delta.get("text") or "")
            if text:
                return text, accum + text, sid
        return None, accum, sid
    if ev == "assistant":
        content = (obj.get("message") or {}).get("content") or []
        bits: list[str] = []
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    t = str(block.get("text") or "")
                    if t:
                        bits.append(t)
        text = "".join(bits)
        if not text:
            return None, accum, sid
        if accum and text.startswith(accum):
            piece = text[len(accum):]
            return (piece or None), text, sid
        if text == accum:
            return None, accum, sid
        return text, accum + text, sid
    if ev in ("end", "result", "error"):
        return None, accum, sid
    return None, accum, sid
