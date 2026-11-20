from devscope_bridge.grok_stream_parser import (
    activities_from_obj,
    parse_line_to_delta,
    session_id_from_obj,
    thoughts_from_obj,
)


def test_text_delta_and_session_id_on_end():
    delta, accum, sid = parse_line_to_delta('{"type":"text","data":"Hello"}', "")
    assert delta == "Hello"
    assert accum == "Hello"
    assert sid is None
    delta, accum, sid = parse_line_to_delta(
        '{"type":"end","sessionId":"01abc","stopReason":"end_turn"}', accum
    )
    assert delta is None
    assert sid == "01abc"


def test_tool_call_activity():
    started = activities_from_obj({
        "type": "tool_call",
        "toolCallId": "c1",
        "title": "Read",
        "kind": "read",
        "status": "in_progress",
        "toolName": "read_file",
        "rawInput": {"path": "a.py"},
    })
    assert started == [("Read", "read_file", "a.py", "running", "c1")]
    done = activities_from_obj({
        "type": "tool_call_update",
        "toolCallId": "c1",
        "status": "completed",
        "toolName": "read_file",
    })
    assert done[0][3] == "done"
    assert done[0][4] == "c1"


def test_thought_and_stream_event_deltas():
    assert thoughts_from_obj({"type": "thought", "data": "hmm"}) == "hmm"
    delta, accum, _sid = parse_line_to_delta(
        '{"type":"stream_event","event":{"delta":{"type":"text_delta","text":"Hi"}}}',
        "",
    )
    assert delta == "Hi"
    assert accum == "Hi"
    assert thoughts_from_obj({
        "type": "stream_event",
        "event": {"delta": {"type": "thinking_delta", "thinking": "plan"}},
    }) == "plan"


def test_assistant_tool_use_has_call_id():
    acts = activities_from_obj({
        "type": "assistant",
        "message": {
            "content": [{"type": "tool_use", "id": "call_9", "name": "read_file", "input": {"path": "a.py"}}],
        },
    })
    assert acts == [("read_file", "read_file", "a.py", "running", "call_9")]


def test_session_id_from_obj():
    assert session_id_from_obj({"sessionId": "s1"}) == "s1"
    assert session_id_from_obj({"type": "end", "session_id": "s2"}) == "s2"
