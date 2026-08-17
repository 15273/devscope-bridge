"""Tests for cursor-agent stream-json tool activity parsing.

Activity tuples are (label, tool, detail, status), status in
"running" | "done" | "error" — B6 added the done/error transitions so a
started tool_call is no longer left hanging forever (cursor RC-9).
"""

import json

from devscope_bridge.cursor_stream_parser import (
    assistant_tool_activities,
    cursor_tool_activity_from_event,
)


def test_mcp_browser_tool_call_started():
    obj = {
        "type": "tool_call",
        "subtype": "started",
        "tool_call": {
            "mcpToolCall": {
                "toolName": "browser_list_tabs",
                "serverName": "browser-control",
            },
        },
    }
    label, tool, detail, status = cursor_tool_activity_from_event(obj)
    assert label == "list tabs"
    assert tool == "browser_list_tabs"
    assert detail is None
    assert status == "running"


def test_shell_tool_call_started():
    obj = {
        "type": "tool_call",
        "subtype": "started",
        "tool_call": {
            "shellToolCall": {"args": {"command": "npm test"}},
        },
    }
    label, tool, detail, status = cursor_tool_activity_from_event(obj)
    assert label == "Running command"
    assert tool == "shell"
    assert "npm test" in (detail or "")
    assert status == "running"


def test_assistant_tool_use_browser():
    acts = assistant_tool_activities([
        {"type": "tool_use", "name": "browser_snapshot", "input": {}},
    ])
    assert acts == [("snapshot", "browser_snapshot", None, "running")]


def test_tool_call_completed_emits_done_transition():
    """B6 fix: completed tool_calls now surface a done transition instead of
    being dropped — the frontend needs this to close out a running row."""
    obj = {
        "type": "tool_call",
        "subtype": "completed",
        "tool_call": {
            "shellToolCall": {"args": {"command": "npm test"}},
        },
    }
    label, tool, detail, status = cursor_tool_activity_from_event(obj)
    assert status == "done"
    assert tool == "shell"
    assert label == "Running command"
    assert detail is None


def test_tool_call_error_emits_error_transition():
    obj = {
        "type": "tool_call",
        "subtype": "error",
        "tool_call": {
            "shellToolCall": {"args": {"command": "npm test"}, "error": "exit 1"},
        },
    }
    label, tool, detail, status = cursor_tool_activity_from_event(obj)
    assert status == "error"
    assert tool == "shell"
    assert detail == "exit 1"


def test_tool_call_unknown_subtype_ignored():
    obj = {"type": "tool_call", "subtype": "queued", "tool_call": {}}
    assert cursor_tool_activity_from_event(obj) is None


def test_non_tool_call_event_ignored():
    assert cursor_tool_activity_from_event({"type": "assistant"}) is None
    assert cursor_tool_activity_from_event(json.loads('{"type": "result"}')) is None
