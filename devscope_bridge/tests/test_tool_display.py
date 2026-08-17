# MCP tool-name humanization used in the live activity feed.
"""Tests for MCP tool-name humanization used in the live activity feed."""

from __future__ import annotations

from devscope_bridge.tool_display import extract_param_preview, humanize_tool_name


def test_humanize_browser_control_tool():
    server, action = humanize_tool_name("mcp__browser-control__browser_navigate")
    assert server == "Browser"
    assert action == "Navigate"


def test_humanize_whatsapp_control_tool():
    server, action = humanize_tool_name("mcp__whatsapp-control__wa_send")
    assert server == "WhatsApp"
    assert action == "Send"


def test_humanize_meta_ads_control_tool():
    server, action = humanize_tool_name("mcp__meta-ads-control__meta_get_insights")
    assert server == "Meta Ads"
    assert action == "Get Insights"


def test_humanize_task_control_tool_strips_either_prefix():
    assert humanize_tool_name("mcp__task-control__schedule_list") == ("Tasks", "List")
    assert humanize_tool_name("mcp__task-control__task_create") == ("Tasks", "Create")


def test_humanize_non_mcp_tool_passthrough():
    assert humanize_tool_name("Bash") == ("Bash", "")
    assert humanize_tool_name("Read") == ("Read", "")


def test_extract_param_preview_priority_key():
    tool_input = {"selector": "#submit", "url": "https://example.com/apply"}
    preview = extract_param_preview("mcp__browser-control__browser_click", tool_input)
    assert preview == "https://example.com/apply"


def test_extract_param_preview_fallback_to_first_string_value():
    tool_input = {"campaign_ids": [1, 2, 3], "note": "some free text"}
    preview = extract_param_preview("mcp__meta-ads-control__meta_list_campaigns", tool_input)
    assert preview == "some free text"


def test_extract_param_preview_truncates_at_80_chars():
    long_value = "x" * 200
    preview = extract_param_preview("mcp__gmail-control__gm_search_threads", {"query": long_value})
    assert preview == "x" * 80


def test_extract_param_preview_empty_input_returns_none():
    assert extract_param_preview("mcp__browser-control__browser_navigate", {}) is None


def test_extract_param_preview_no_string_values_returns_none():
    tool_input = {"count": 5, "enabled": True}
    assert extract_param_preview("mcp__task-control__task_create", tool_input) is None


def test_extract_param_preview_non_mcp_tool_returns_none():
    assert extract_param_preview("Bash", {"command": "ls -la"}) is None
