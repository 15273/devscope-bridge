"""
Sanity check that whatsapp_mcp_server loads and exposes the expected tool set.
"""


def test_imports_and_tools():
    from devscope_bridge.whatsapp_mcp_server import mcp
    assert mcp is not None


def test_mcp_instance_named_correctly():
    from devscope_bridge.whatsapp_mcp_server import mcp
    assert mcp.name == "whatsapp-control"


def test_expected_tools_registered():
    from devscope_bridge.whatsapp_mcp_server import mcp
    registered = {t.name for t in mcp._tool_manager.list_tools()}
    expected = {
        "wa_list_chats", "wa_get_messages", "wa_search",
        "wa_nudges", "wa_send", "wa_mark_read", "wa_ask",
    }
    assert expected == registered
