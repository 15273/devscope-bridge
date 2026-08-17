"""
Sanity check that browser_mcp_server loads and exposes the expected tool set.
"""

import pytest

from devscope_bridge.browser_mcp_server import mcp, TOOL_NAMES


def test_module_imports():
    """The MCP server module must import without errors."""
    import devscope_bridge.browser_mcp_server  # noqa: F401


def test_tool_count_matches_spec():
    """Tool count must match TOOL_NAMES registry."""
    assert len(TOOL_NAMES) == 28


def test_expected_tool_names():
    """All spec tool names must be present in TOOL_NAMES."""
    expected = {
        # v1 tools
        "browser_navigate",
        "browser_screenshot",
        "browser_get_page_info",
        "browser_list_tabs",
        "browser_focus_tab",
        "browser_click",
        "browser_fill",
        "browser_get_elements",
        "browser_evaluate",
        "browser_snapshot",
        "browser_get_network",
        "browser_get_console",
        # v2 tools
        "browser_highlight",
        "browser_wait_for_selector",
        "browser_wait_for_navigation",
        "browser_assert_text",
        "browser_scroll_to",
        "browser_select_option",
        "browser_hover",
        "browser_key_press",
        # cross-profile / tab management
        "browser_new_page",
        "browser_upload_file",
        # LinkedIn tools
        "linkedin_scrape_feed",
        "linkedin_fill_composer",
        "linkedin_fill_comment",
        "linkedin_scrape_people_search",
        "linkedin_read_search_state",
        "linkedin_scrape_profile",
    }
    assert set(TOOL_NAMES) == expected


def test_mcp_instance_created():
    """The FastMCP instance must exist and be named correctly."""
    assert mcp.name == "browser-control"


def test_registered_tools_match_spec():
    """Tools registered in the MCP server must match the TOOL_NAMES list."""
    # FastMCP stores registered tools in _tool_manager
    registered_names = {t.name for t in mcp._tool_manager.list_tools()}
    for name in TOOL_NAMES:
        assert name in registered_names, f"Tool '{name}' not found in MCP server"
