"""tool_display.py — Human-readable labels for MCP tool_use blocks.

Pure functions, no imports from session_reader.py (session_reader imports
FROM this module, never the reverse, to avoid circular imports).

MCP tool names are shaped like ``mcp__<server-slug>__<action>``
(e.g. ``mcp__browser-control__browser_navigate``). This module turns that
into a short server label ("Browser") + a humanized action label
("Navigate"), plus a best-effort one-line parameter preview.
"""

# MCP server slug -> short human label shown in the transcript.
SERVER_LABELS: dict[str, str] = {
    "browser-control": "Browser",
    "whatsapp-control": "WhatsApp",
    "gmail-control": "Gmail",
    "calendar-control": "Calendar",
    "meta-ads-control": "Meta Ads",
    "task-control": "Tasks",
}

# MCP server slug -> action-name prefixes to strip (checked in order).
_ACTION_PREFIXES: dict[str, tuple[str, ...]] = {
    "browser-control": ("browser_",),
    "whatsapp-control": ("wa_",),
    "gmail-control": ("gm_",),
    "calendar-control": ("cal_",),
    "meta-ads-control": ("meta_",),
    "task-control": ("schedule_", "task_"),
}

# tool_input keys checked (in priority order) for a one-line param preview.
_PREVIEW_KEYS: tuple[str, ...] = (
    "url",
    "selector",
    "query",
    "chat_name",
    "campaign_id",
    "ad_account_id",
    "summary",
    "text",
    "message",
)

_PREVIEW_MAX_LEN = 80


def _split_mcp_tool(raw_tool: str) -> tuple[str, str] | None:
    """Split ``mcp__<server>__<action>`` into (server, action), or None."""
    if not raw_tool.startswith("mcp__"):
        return None
    parts = raw_tool.split("__", 2)
    if len(parts) != 3:
        return None
    return parts[1], parts[2]


def humanize_tool_name(raw_tool: str) -> tuple[str, str]:
    """Return (server_label, action_label) for an MCP tool name.

    Non-MCP tool names (Bash, Read, Write, Task, Grep, ...) pass through
    unchanged as (raw_tool, "") — their existing display logic is untouched.
    """
    split = _split_mcp_tool(raw_tool)
    if split is None:
        return (raw_tool, "")

    server, action = split
    server_label = SERVER_LABELS.get(server, server.replace("-", " ").title())

    for prefix in _ACTION_PREFIXES.get(server, ()):
        if action.startswith(prefix) and len(action) > len(prefix):
            action = action[len(prefix):]
            break

    action_label = action.replace("_", " ").title()
    return (server_label, action_label)


def extract_param_preview(raw_tool: str, tool_input: dict) -> str | None:
    """Return a short (~80 char) preview of the most relevant param.

    Only applies to MCP tools. Checks a fixed priority list of keys first,
    then falls back to the first string-valued key present. Returns None
    when there is nothing to show.
    """
    if _split_mcp_tool(raw_tool) is None:
        return None
    if not tool_input:
        return None

    for key in _PREVIEW_KEYS:
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            return value[:_PREVIEW_MAX_LEN]

    for value in tool_input.values():
        if isinstance(value, str) and value:
            return value[:_PREVIEW_MAX_LEN]

    return None
