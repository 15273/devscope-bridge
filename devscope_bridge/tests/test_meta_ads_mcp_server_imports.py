"""Sanity check meta_ads_mcp_server tools."""


def test_mcp_named():
    from devscope_bridge.meta_ads_mcp_server import mcp
    assert mcp.name == "meta-ads-control"


def test_expected_tools():
    from devscope_bridge.meta_ads_mcp_server import mcp
    registered = {t.name for t in mcp._tool_manager.list_tools()}
    expected = {
        "meta_list_accounts",
        "meta_list_campaigns",
        "meta_get_insights",
        "meta_update_campaign_status",
        "meta_update_campaign_budget",
        "meta_list_alerts",
    }
    assert expected == registered
