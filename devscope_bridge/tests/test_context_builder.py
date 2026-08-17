"""Tests for context_builder bound-tab preamble."""

from devscope_bridge.context_builder import build_context_preamble
from devscope_bridge.models import BoundTabContext, MessageContext


def test_bound_tab_included_in_preamble():
    ctx = MessageContext(
        boundTab=BoundTabContext(
            tabId=668837580,
            url="https://console.aws.amazon.com/ses/home",
            title="Account dashboard",
            windowId=668837409,
        ),
    )
    preamble = build_context_preamble(ctx)
    assert "BROWSER TAB BOUND" in preamble
    assert "668837580" in preamble
    assert "668837409" in preamble
    assert "console.aws.amazon.com" in preamble
    assert "WITHOUT tab_id" in preamble
