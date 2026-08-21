from devscope_bridge.orchestrator_core import _next_run_at


def test_daily_at_no_drift():
    # Tick fired late at 09:07 for a 09:00 schedule → next is tomorrow 09:00 sharp.
    nxt = _next_run_at({"daily_at": "09:00"}, "2026-08-21 09:07:33",
                       anchor="2026-08-21 09:00:00")
    assert nxt == "2026-08-22 09:00:00"


def test_every_minutes_anchored():
    nxt = _next_run_at({"every_minutes": 30}, "2026-08-21 10:07:00",
                       anchor="2026-08-21 10:00:00")
    assert nxt == "2026-08-21 10:30:00"


def test_every_minutes_skips_missed_slots():
    # Bridge was down for 2h → next slot is in the future, not a backlog burst.
    nxt = _next_run_at({"every_minutes": 30}, "2026-08-21 12:05:00",
                       anchor="2026-08-21 10:00:00")
    assert nxt == "2026-08-21 12:30:00"


def test_weekly_at():
    # 2026-08-21 is a Friday (weekday 4). Next Monday 08:00 → 2026-08-24.
    nxt = _next_run_at({"weekly_at": {"day": 0, "time": "08:00"}}, "2026-08-21 10:00:00")
    assert nxt == "2026-08-24 08:00:00"


def test_missing_recurrence_defaults_hour():
    assert _next_run_at({}, "2026-08-21 10:00:00") == "2026-08-21 11:00:00"
