"""
test_watchdog_subagent_caps.py — FIX 2: live Task/Agent sub-agents exempt a
turn from the silence and wall hard-caps (a parent waiting on sub-agents is
legitimately long and often silent). The absolute ceiling ALWAYS applies.

Covers the pure decision helper compute_hard_due() plus one watchdog-loop
integration test proving that with sub-agents in flight the wall cap is
skipped but the absolute cap still interrupts (with an accurate reason).
"""

import asyncio
import pytest

import devscope_bridge.session_reader as sr
from devscope_bridge.models import AiError


# ─────────────────────────────────────────────
# Pure decision helper
# ─────────────────────────────────────────────

def test_compute_hard_due_subagents_in_flight_only_absolute():
    kw = {"long_running": False, "subagents_in_flight": True}
    assert sr.compute_hard_due(True, False, False, **kw) is False
    assert sr.compute_hard_due(False, True, False, **kw) is False
    assert sr.compute_hard_due(True, True, False, **kw) is False
    assert sr.compute_hard_due(False, False, True, **kw) is True
    # Sub-agents win over long_running: still only absolute.
    assert sr.compute_hard_due(True, True, False, long_running=True, subagents_in_flight=True) is False


def test_compute_hard_due_long_running_wall_or_absolute():
    kw = {"long_running": True, "subagents_in_flight": False}
    assert sr.compute_hard_due(True, False, False, **kw) is False
    assert sr.compute_hard_due(False, True, False, **kw) is True
    assert sr.compute_hard_due(False, False, True, **kw) is True


def test_compute_hard_due_default_any_cap():
    kw = {"long_running": False, "subagents_in_flight": False}
    assert sr.compute_hard_due(False, False, False, **kw) is False
    assert sr.compute_hard_due(True, False, False, **kw) is True
    assert sr.compute_hard_due(False, True, False, **kw) is True
    assert sr.compute_hard_due(False, False, True, **kw) is True


# ─────────────────────────────────────────────
# Watchdog loop integration
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_watchdog_skips_wall_cap_with_subagents_but_absolute_fires(monkeypatch):
    """With sub-agents in flight, silence/wall caps are skipped; absolute fires."""
    monkeypatch.setattr(sr, "_WATCHDOG_HEARTBEAT_S", 0.05)
    monkeypatch.setattr(sr, "_WATCHDOG_MEDIC_S", 99.0)
    monkeypatch.setattr(sr, "_WATCHDOG_HARD_CAP_S", 0.05)   # would fire instantly if counted
    monkeypatch.setattr(sr, "_WATCHDOG_TURN_WALL_MEDIC_S", 99.0)
    monkeypatch.setattr(sr, "_WATCHDOG_TURN_WALL_CAP_S", 0.1)
    monkeypatch.setattr(sr, "_WATCHDOG_TURN_ABSOLUTE_CAP_S", 0.45)
    monkeypatch.setattr(sr.sub_agent_tracker, "has_in_flight", lambda _n: True)

    q: asyncio.Queue = asyncio.Queue()
    activity_event = asyncio.Event()
    turn_active = asyncio.Event()
    turn_active.set()
    interrupt_called: list[bool] = []

    watchdog = asyncio.create_task(sr._watchdog_loop(
        "subagent-sess", q, activity_event,
        hard_interrupt_fn=lambda: interrupt_called.append(True),
        turn_active_event=turn_active,
    ))
    await asyncio.sleep(0.25)
    assert not interrupt_called, "silence/wall caps must not fire while sub-agents in flight"
    await asyncio.sleep(0.45)
    watchdog.cancel()
    try:
        await watchdog
    except asyncio.CancelledError:
        pass

    assert interrupt_called, "absolute cap must still interrupt with sub-agents in flight"
    frames = []
    while not q.empty():
        frames.append(q.get_nowait())
    errors = [f for f in frames if isinstance(f, AiError)]
    assert errors, f"Expected AiError from absolute cap: {frames}"
    assert "absolute" in errors[0].stderr_tail, \
        f"Reason must name the absolute cap: {errors[0].stderr_tail!r}"
