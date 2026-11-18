from devscope_bridge.browser_filters import (
    filter_console,
    filter_network,
    normalize_since_ms,
)


def test_normalize_since_ms_seconds_and_millis():
    assert normalize_since_ms(1_700_000_000) == 1_700_000_000_000
    assert normalize_since_ms(1_700_000_000_500) == 1_700_000_000_500
    assert normalize_since_ms(None) is None


def test_filter_console_by_tab_and_since():
    payload = {
        "entries": [
            {"ts": 1_700_000_000_000, "tab_id": 1, "text": "old-1"},
            {"ts": 1_700_000_010_000, "tab_id": 2, "text": "new-2"},
            {"ts": 1_700_000_020_000, "tab_id": 1, "text": "new-1"},
        ]
    }
    out = filter_console(payload, tab_id=1, since_ts=1_700_000_005)
    assert [e["text"] for e in out["entries"]] == ["new-1"]
    assert out["count"] == 1


def test_filter_network_uses_wall_ts_and_time_origin():
    origin = 1_700_000_000_000
    payload = {
        "timeOrigin": origin,
        "resources": [
            {"name": "https://a.example/early.js", "startMs": 50, "tab_id": 9},
            {"name": "https://a.example/late.js", "startMs": 4000, "tab_id": 9},
            {"name": "https://a.example/other.js", "startMs": 4000, "tab_id": 8},
        ],
    }
    out = filter_network(payload, tab_id=9, since_ts=1_700_000_001)
    assert [r["name"] for r in out["resources"]] == ["https://a.example/late.js"]
