"""Sanity check that calendar_mcp_server loads and exposes tools."""


def test_imports_and_tools():
    from devscope_bridge.calendar_mcp_server import mcp
    assert mcp is not None


def test_mcp_instance_named_correctly():
    from devscope_bridge.calendar_mcp_server import mcp
    assert mcp.name == "calendar-control"


def test_expected_tools_registered():
    from devscope_bridge.calendar_mcp_server import mcp
    registered = {t.name for t in mcp._tool_manager.list_tools()}
    expected = {
        "cal_list_events",
        "cal_get_event",
        "cal_find_free_slots",
        "cal_validate_event_draft",
        "cal_create_event",
    }
    assert expected == registered
