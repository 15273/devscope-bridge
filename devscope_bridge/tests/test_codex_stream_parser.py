from devscope_bridge.codex_stream_parser import activities_from_obj, parse_line_to_delta, session_id_from_obj


def test_thread_started_id():
    obj = {"type": "thread.started", "thread_id": "thr_abc"}
    assert session_id_from_obj(obj) == "thr_abc"
    delta, accum, sid = parse_line_to_delta(
        '{"type":"thread.started","thread_id":"thr_abc"}', ""
    )
    assert delta is None
    assert sid == "thr_abc"
    assert accum == ""


def test_agent_message_completed():
    line = '{"type":"item.completed","item":{"type":"agent_message","text":"hello"}}'
    delta, accum, _ = parse_line_to_delta(line, "")
    assert delta == "hello"
    assert accum == "hello"
    delta2, accum2, _ = parse_line_to_delta(
        '{"type":"item.completed","item":{"type":"agent_message","text":"hello world"}}',
        "hello",
    )
    assert delta2 == " world"
    assert accum2 == "hello world"


def test_command_activity():
    started = {
        "type": "item.started",
        "item": {"type": "command_execution", "command": "ls", "cwd": "/tmp"},
    }
    rows = activities_from_obj(started)
    assert rows == [("ls", "commandexecution", "/tmp", "running")]
