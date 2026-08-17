"""
Shared fixtures for dev_bridge tests.

Patches out the token read so tests don't need ~/.dev-bridge/token to exist.
"""

import sys
import os
from pathlib import Path

# Repo root (devscope/) so `import devscope_bridge` resolves.
_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import pytest


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "empirical: spawns a REAL claude process — skipped unless RUN_EMPIRICAL=1",
    )


def pytest_collection_modifyitems(config, items):
    """Skip empirical (real-claude) tests by default; opt in with RUN_EMPIRICAL=1."""
    if os.environ.get("RUN_EMPIRICAL") == "1":
        return
    skip = pytest.mark.skip(reason="empirical: set RUN_EMPIRICAL=1 to run (spawns real claude)")
    for item in items:
        if "empirical" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def patch_startup_token(monkeypatch):
    """
    Replace the bridge startup token with a known value for all tests.
    Also keeps _active_ws and _pending_actions clean between tests.
    """
    import devscope_bridge.main as bridge_main
    import devscope_bridge.browser_relay as relay

    monkeypatch.setattr(bridge_main, "_startup_token", "test-token-abc123")
    relay._active_ws.clear()
    relay._pending_actions.clear()
    relay._action_session.clear()
    yield
    relay._active_ws.clear()
    relay._pending_actions.clear()
    relay._action_session.clear()
