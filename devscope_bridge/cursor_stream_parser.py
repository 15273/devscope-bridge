"""Parse cursor-agent stream-json lines for UI activity frames."""

from __future__ import annotations

from typing import Any

# Activity tuple shape: (label, tool, detail, status).
# status is one of "running" | "done" | "error" — mirrors AgentActivity.status
# so the panel can render one row that transitions in place (B6).
ActivityTuple = tuple[str, str, str | None, str | None]


def _tool_meta(key: str, payload: dict[str, Any], args: dict[str, Any]) -> tuple[str, str, str | None]:
    """Return (label, tool_name, detail) for one tool_call variant key."""
    if "mcp" in key.lower():
        tool_name = (
            payload.get("toolName")
            or payload.get("tool")
            or args.get("toolName")
            or args.get("name")
            or key
        )
        name = str(tool_name)
        if name.startswith("browser_"):
            return name.removeprefix("browser_").replace("_", " "), name, None
        server = payload.get("serverName") or payload.get("server") or "mcp"
        return str(server), name, None

    if key == "shellToolCall":
        cmd = (args or {}).get("command", "")
        return "Running command", "shell", str(cmd)[:80] or None
    if key == "readToolCall":
        path = (args or {}).get("path") or (args or {}).get("target_file", "")
        return "Reading", "read", str(path) or None
    if key in ("writeToolCall", "editToolCall"):
        path = (args or {}).get("path") or (args or {}).get("target_file", "")
        return "Editing", key, str(path) or None
    if key == "searchToolCall":
        query = (args or {}).get("query") or (args or {}).get("pattern", "")
        return "Searching", "search", str(query)[:80] or None

    short = key.replace("ToolCall", "").replace("Call", "")
    return short or "Tool", key, None


def cursor_tool_activity_from_event(obj: dict[str, Any]) -> ActivityTuple | None:
    """Map a cursor `tool_call` started/completed/error event to an activity tuple.

    Emits a "running" activity on `started` and a "done"/"error" transition on
    `completed`/`error` so the UI (and current_tool tracking) can close the loop
    instead of leaving a tool call hanging forever (cursor RC-9).
    """
    if obj.get("type") != "tool_call":
        return None
    subtype = obj.get("subtype")
    if subtype not in ("started", "completed", "error"):
        return None

    tool_call = obj.get("tool_call")
    if not isinstance(tool_call, dict):
        return None

    for key, payload in tool_call.items():
        if not isinstance(payload, dict):
            continue
        args = payload.get("args") if isinstance(payload.get("args"), dict) else payload
        label, tool_name, detail = _tool_meta(key, payload, args)

        if subtype == "started":
            return label, tool_name, detail, "running"
        if subtype == "completed":
            return label, tool_name, None, "done"

        err = payload.get("error") or payload.get("message") or ""
        return label, tool_name, (str(err)[:200] or None), "error"

    return None


def assistant_tool_activities(content: list[Any]) -> list[ActivityTuple]:
    """Claude-compatible tool_use blocks inside assistant messages.

    These arrive already "in flight" within the assistant message (cursor-agent
    doesn't emit a separate started event for them), so they are always
    reported as status="running".
    """
    out: list[ActivityTuple] = []
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "tool_use":
            continue
        tool_name = str(block.get("name", "tool"))
        inp = block.get("input") if isinstance(block.get("input"), dict) else {}
        if tool_name.startswith("browser_"):
            label = tool_name.removeprefix("browser_").replace("_", " ")
            out.append((label, tool_name, None, "running"))
        elif tool_name.startswith("mcp__browser-control__"):
            short = tool_name.split("__")[-1].removeprefix("browser_").replace("_", " ")
            out.append((short, tool_name, None, "running"))
        elif tool_name == "Bash":
            out.append(("Running command", tool_name, str(inp.get("command", ""))[:80] or None, "running"))
        else:
            out.append((tool_name, tool_name, None, "running"))
    return out
