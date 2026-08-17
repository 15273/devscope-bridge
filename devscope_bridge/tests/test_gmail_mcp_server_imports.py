"""
Sanity check that gmail_mcp_server loads and exposes the expected tool set.
"""


def test_imports_and_tools():
    from devscope_bridge.gmail_mcp_server import mcp
    assert mcp is not None


def test_mcp_instance_named_correctly():
    from devscope_bridge.gmail_mcp_server import mcp
    assert mcp.name == "gmail-control"


def test_expected_tools_registered():
    from devscope_bridge.gmail_mcp_server import mcp
    registered = {t.name for t in mcp._tool_manager.list_tools()}
    expected = {"gm_search_threads", "gm_get_thread", "gm_list_labels"}
    assert expected == registered
