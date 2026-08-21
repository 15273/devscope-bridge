import pytest
from unittest.mock import AsyncMock, patch
from devscope_bridge import session_runner


@pytest.mark.asyncio
async def test_run_turn_updates_stored_agent(tmp_path):
    with patch.object(session_runner.session_store, "get_session",
                      return_value={"name": "worker-x", "agent": "claude"}), \
         patch.object(session_runner.session_store, "set_session_agent") as set_agent, \
         patch.object(session_runner.session_manager, "run_prompt", new=AsyncMock()), \
         patch.object(session_runner.BridgeSessionRunner, "_await_turn",
                      new=AsyncMock(return_value=True)):
        ok = await session_runner.BridgeSessionRunner().run_turn(
            "worker-x", "go", agent="cursor")
    assert ok
    set_agent.assert_called_once_with("worker-x", "cursor")
