import json

from devscope_bridge.agy_stream_parser import (
    activities_from_obj,
    parse_line_to_delta,
)


SID = "9ec58bfd-4d67-4f5e-83a5-9d907e9c6b1f"


def test_official_stream_json_sequence():
    init = {"event": "init", "conversation_id": SID, "init": {"cwd": "/repo"}}
    delta_event = {
        "event": "step_update",
        "step_update": {
            "conversation_id": SID,
            "step_index": 2,
            "state": "ACTIVE",
            "step_type": "agent_response",
            "text_delta": "apple",
        },
    }
    result = {
        "event": "result",
        "result": {
            "conversation_id": SID,
            "status": "SUCCESS",
            "response": "apple\n",
        },
    }

    delta, accum, sid = parse_line_to_delta(json.dumps(init), "")
    assert (delta, accum, sid) == (None, "", SID)
    delta, accum, sid = parse_line_to_delta(json.dumps(delta_event), accum)
    assert (delta, accum, sid) == ("apple", "apple", SID)
    delta, accum, sid = parse_line_to_delta(json.dumps(result), accum)
    assert (delta, accum, sid) == ("\n", "apple\n", SID)


def test_step_activity_uses_nested_official_shape():
    event = {
        "event": "step_update",
        "step_update": {"state": "ACTIVE", "step_type": "run_command"},
    }
    assert activities_from_obj(event) == [
        ("run_command", "run_command", None, "running")
    ]
