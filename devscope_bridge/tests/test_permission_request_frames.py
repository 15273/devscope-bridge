"""
test_permission_request_frames.py

Tests for permission/approval detection in the bridge:

1. dispatch_event emits PermissionRequest(kind="plan") when it sees an
   assistant event with an ExitPlanMode tool_use block.
2. dispatch_event still emits AiDone for the turn after the plan request.
3. dispatch_event emits PermissionRequest(kind="permission_denied") for
   non-ExitPlanMode entries in the result.permission_denials array.
4. ExitPlanMode entries in permission_denials are NOT re-emitted (already
   surfaced as kind="plan").
5. session_manager.send_approval writes "yes proceed" to stdin for "approve".
6. session_manager.send_approval does NOT write to stdin for "deny".
7. main.py _ws_receive_loop handles permission_response frames by calling
   send_approval.
"""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import devscope_bridge.session_store as store
import devscope_bridge.session_manager as mgr
from devscope_bridge import session_reader
from devscope_bridge.models import (
    AiDone, AiError, AgentActivity, PermissionRequest, SessionReady, TurnState,
)


# ─────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────

@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "SESSIONS_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(store, "BRIDGE_DIR", tmp_path)
    mgr._sessions.clear()
    session_reader._pending_permissions.clear()
    yield
    mgr._sessions.clear()
    session_reader._pending_permissions.clear()


def _assistant_event(content: list, sid: str = "s1") -> dict:
    return {
        "type": "assistant",
        "message": {"role": "assistant", "content": content},
        "session_id": sid,
    }


def _exit_plan_mode_block(
    tool_id: str = "toolu_abc",
    plan: str = "# Plan\nStep 1: do thing",
    plan_file: str = "/home/.claude/plans/plan.md",
) -> dict:
    return {
        "type": "tool_use",
        "id": tool_id,
        "name": "ExitPlanMode",
        "input": {"plan": plan, "planFilePath": plan_file},
    }


def _result_event(
    subtype: str = "success",
    is_error: bool = False,
    permission_denials: list | None = None,
    sid: str = "s1",
) -> dict:
    return {
        "type": "result",
        "subtype": subtype,
        "is_error": is_error,
        "result": "done",
        "session_id": sid,
        "permission_denials": permission_denials or [],
        "usage": {},
        "total_cost_usd": 0,
        "duration_ms": 0,
    }


async def _drain(q: asyncio.Queue, timeout: float = 1.0) -> list:
    frames = []
    try:
        async with asyncio.timeout(timeout):
            while True:
                frames.append(q.get_nowait())
    except (asyncio.QueueEmpty, TimeoutError):
        pass
    return frames


# ─────────────────────────────────────────────
# Test 1: ExitPlanMode → PermissionRequest(kind="plan") emitted
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_exit_plan_mode_emits_permission_request():
    """ExitPlanMode tool_use in assistant event emits PermissionRequest(kind="plan")."""
    q: asyncio.Queue = asyncio.Queue()
    block = _exit_plan_mode_block(plan="# Plan\nStep 1: create file")
    event = _assistant_event([block])

    done = await session_reader.dispatch_event("sess", event, q, is_first_message=False)
    assert done is False  # assistant event does not end the turn

    frames = await _drain(q)

    perm_frames = [f for f in frames if isinstance(f, PermissionRequest)]
    assert len(perm_frames) == 1, f"Expected 1 PermissionRequest, got: {frames}"

    pr = perm_frames[0]
    assert pr.kind == "plan"
    assert pr.session == "sess"
    assert pr.description == "# Plan\nStep 1: create file"
    assert pr.plan_file_path == "/home/.claude/plans/plan.md"
    assert len(pr.options) == 2
    option_ids = {o.id for o in pr.options}
    assert "approve" in option_ids
    assert "deny" in option_ids


@pytest.mark.asyncio
async def test_exit_plan_mode_request_id_stored_in_pending():
    """The PermissionRequest's request_id is stored in _pending_permissions."""
    q: asyncio.Queue = asyncio.Queue()
    block = _exit_plan_mode_block()
    event = _assistant_event([block])

    await session_reader.dispatch_event("sess", event, q, is_first_message=False)
    frames = await _drain(q)
    perm_frames = [f for f in frames if isinstance(f, PermissionRequest)]
    assert len(perm_frames) == 1

    rid = perm_frames[0].request_id
    assert rid in session_reader._pending_permissions
    assert session_reader._pending_permissions[rid]["kind"] == "plan"


# ─────────────────────────────────────────────
# Test 2: Plan PermissionRequest + AiDone both emitted in same turn
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_plan_request_then_ai_done():
    """PermissionRequest(kind="plan") is emitted, then AiDone for the same turn."""
    q: asyncio.Queue = asyncio.Queue()

    # Simulate: assistant event with ExitPlanMode, then result event
    assistant_ev = _assistant_event([_exit_plan_mode_block()])
    result_ev = _result_event(permission_denials=[{
        "tool_name": "ExitPlanMode",
        "tool_use_id": "toolu_abc",
        "tool_input": {"plan": "# Plan\nStep 1", "planFilePath": "/path/plan.md"},
    }])

    await session_reader.dispatch_event("sess", assistant_ev, q, is_first_message=False)
    done = await session_reader.dispatch_event("sess", result_ev, q, is_first_message=False)

    assert done is True
    frames = await _drain(q)

    types = [type(f).__name__ for f in frames]
    assert "PermissionRequest" in types, f"Missing PermissionRequest: {types}"
    assert "AiDone" in types, f"Missing AiDone: {types}"
    assert "AiError" not in types, f"Unexpected AiError: {types}"

    # PermissionRequest appears before AiDone
    pr_idx = next(i for i, f in enumerate(frames) if isinstance(f, PermissionRequest))
    done_idx = next(i for i, f in enumerate(frames) if isinstance(f, AiDone))
    assert pr_idx < done_idx, "PermissionRequest must come before AiDone"


# ─────────────────────────────────────────────
# Test 3: ExitPlanMode in permission_denials is NOT re-emitted
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_exit_plan_mode_denial_not_re_emitted():
    """ExitPlanMode in permission_denials is skipped (already surfaced by assistant event)."""
    q: asyncio.Queue = asyncio.Queue()
    result_ev = _result_event(permission_denials=[{
        "tool_name": "ExitPlanMode",
        "tool_use_id": "toolu_abc",
        "tool_input": {"plan": "plan text"},
    }])

    await session_reader.dispatch_event("sess", result_ev, q, is_first_message=False)
    frames = await _drain(q)

    perm_frames = [f for f in frames if isinstance(f, PermissionRequest)]
    assert len(perm_frames) == 0, f"ExitPlanMode denial should NOT be re-emitted: {perm_frames}"

    assert any(isinstance(f, AiDone) for f in frames)


# ─────────────────────────────────────────────
# Test 4: Non-ExitPlanMode permission_denials emit PermissionRequest(kind="permission_denied")
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_non_plan_permission_denial_emitted():
    """Bash denial in permission_denials emits PermissionRequest(kind="permission_denied")."""
    q: asyncio.Queue = asyncio.Queue()
    result_ev = _result_event(permission_denials=[
        {
            "tool_name": "Bash",
            "tool_use_id": "toolu_bash",
            "tool_input": {"command": "rm -rf /"},
        },
        {
            "tool_name": "Write",
            "tool_use_id": "toolu_write",
            "tool_input": {"file_path": "/etc/passwd", "content": "hack"},
        },
    ])

    await session_reader.dispatch_event("sess", result_ev, q, is_first_message=False)
    frames = await _drain(q)

    perm_frames = [f for f in frames if isinstance(f, PermissionRequest)]
    assert len(perm_frames) == 2, f"Expected 2 denial notices, got: {perm_frames}"

    for pr in perm_frames:
        assert pr.kind == "permission_denied"
        assert len(pr.options) == 0  # no approval possible
        assert "rm -rf" in pr.description or "etc/passwd" in pr.description


@pytest.mark.asyncio
async def test_mixed_denials_only_non_plan_emitted():
    """ExitPlanMode + Bash in permission_denials: only Bash is emitted."""
    q: asyncio.Queue = asyncio.Queue()
    result_ev = _result_event(permission_denials=[
        {"tool_name": "ExitPlanMode", "tool_use_id": "t1", "tool_input": {"plan": "p"}},
        {"tool_name": "Bash", "tool_use_id": "t2", "tool_input": {"command": "ls"}},
    ])

    await session_reader.dispatch_event("sess", result_ev, q, is_first_message=False)
    frames = await _drain(q)

    perm_frames = [f for f in frames if isinstance(f, PermissionRequest)]
    assert len(perm_frames) == 1
    assert perm_frames[0].kind == "permission_denied"
    assert "Bash" in perm_frames[0].title


# ─────────────────────────────────────────────
# Test 5: send_approval writes "yes proceed" for "approve"
# ─────────────────────────────────────────────

class _FakeAsyncIterator:
    def __init__(self):
        self._items = []
        self._idx = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._idx >= len(self._items):
            raise StopAsyncIteration
        item = self._items[self._idx]
        self._idx += 1
        return item


def _make_fake_proc():
    proc = MagicMock()
    proc.pid = 99999
    proc.returncode = None
    proc.stdout = _FakeAsyncIterator()
    proc.stderr = AsyncMock()
    proc.stderr.read = AsyncMock(return_value=b"")
    proc.stdin = MagicMock()
    proc.stdin.write = MagicMock()
    proc.stdin.drain = AsyncMock()

    async def _wait():
        return 0
    proc.wait = _wait
    return proc


@pytest.mark.asyncio
async def test_send_approval_writes_yes_proceed_to_stdin():
    """send_approval(option_id='approve') writes 'yes proceed' to process stdin."""
    proc = _make_fake_proc()

    async def fake_spawn(*args, **kwargs):
        return proc

    with patch("devscope_bridge.session_manager.asyncio.create_subprocess_exec",
               side_effect=fake_spawn):
        await mgr.run_prompt("perm-sess", "make a plan")

    # Simulate a pending permission request
    request_id = "test-req-001"
    session_reader._pending_permissions[request_id] = {"session": "perm-sess", "kind": "plan"}

    result = await mgr.send_approval("perm-sess", request_id, "approve")
    assert result is True

    # stdin.write called twice: once for the prompt, once for the approval
    assert proc.stdin.write.call_count == 2, f"Expected 2 writes, got {proc.stdin.write.call_count}"

    # Second write must be the "yes proceed" message
    second_write_bytes: bytes = proc.stdin.write.call_args_list[1][0][0]
    payload = json.loads(second_write_bytes.decode("utf-8").strip())
    assert payload["type"] == "user"
    text = payload["message"]["content"][0]["text"]
    assert "proceed" in text.lower(), f"Unexpected approval text: {text!r}"

    # Pending permission cleaned up
    assert request_id not in session_reader._pending_permissions


@pytest.mark.asyncio
async def test_send_approval_deny_does_not_write_stdin():
    """send_approval(option_id='deny') does NOT write to stdin."""
    proc = _make_fake_proc()

    async def fake_spawn(*args, **kwargs):
        return proc

    with patch("devscope_bridge.session_manager.asyncio.create_subprocess_exec",
               side_effect=fake_spawn):
        await mgr.run_prompt("deny-sess", "make a plan")

    initial_write_count = proc.stdin.write.call_count  # 1 for the prompt

    request_id = "test-req-002"
    session_reader._pending_permissions[request_id] = {"session": "deny-sess", "kind": "plan"}

    result = await mgr.send_approval("deny-sess", request_id, "deny")
    assert result is True
    assert proc.stdin.write.call_count == initial_write_count  # no new writes


@pytest.mark.asyncio
async def test_send_approval_returns_false_when_session_not_active():
    """send_approval returns False if there is no active process for the session."""
    result = await mgr.send_approval("nonexistent-sess", "req-999", "approve")
    assert result is False


# ─────────────────────────────────────────────
# Test 6: main.py permission_response frame handling
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ws_permission_response_calls_send_approval():
    """WS receives permission_response frame → send_approval is called."""
    from devscope_bridge.main import _ws_receive_loop
    import devscope_bridge.session_manager as sm

    received_args = []

    async def fake_send_approval(name, request_id, option_id, **kwargs):
        received_args.append((name, request_id, option_id, kwargs))
        return True

    # Create a minimal fake WS that sends one permission_response then disconnects
    from fastapi import WebSocketDisconnect

    frames = [
        json.dumps({
            "type": "permission_response",
            "request_id": "req-ws-001",
            "option_id": "approve",
        }),
    ]
    call_count = [0]

    class _FakeWS:
        async def receive_text(self):
            if call_count[0] < len(frames):
                f = frames[call_count[0]]
                call_count[0] += 1
                return f
            raise WebSocketDisconnect(code=1000)

        async def send_text(self, text: str):
            pass  # ignore outbound frames

    with patch.object(sm, "send_approval", side_effect=fake_send_approval):
        try:
            await _ws_receive_loop(_FakeWS(), "test-ws-sess")
        except Exception:
            pass

    assert len(received_args) == 1, f"Expected send_approval called once: {received_args}"
    name, rid, opt, _kwargs = received_args[0]
    assert name == "test-ws-sess"
    assert rid == "req-ws-001"
    assert opt == "approve"


@pytest.mark.asyncio
async def test_ws_invalid_permission_response_sends_error():
    """Malformed permission_response frame triggers an error response."""
    from devscope_bridge.main import _ws_receive_loop
    from fastapi import WebSocketDisconnect

    sent = []

    frames = [
        json.dumps({"type": "permission_response", "bad_field": "no_request_id"}),
    ]
    call_count = [0]

    class _FakeWS:
        async def receive_text(self):
            if call_count[0] < len(frames):
                f = frames[call_count[0]]
                call_count[0] += 1
                return f
            raise WebSocketDisconnect(code=1000)

        async def send_text(self, text: str):
            sent.append(json.loads(text))

    try:
        await _ws_receive_loop(_FakeWS(), "err-sess")
    except Exception:
        pass

    error_frames = [f for f in sent if f.get("type") == "error"]
    assert len(error_frames) >= 1, f"Expected error frame: {sent}"


# ─────────────────────────────────────────────
# Test 7: AskUserQuestion → PermissionRequest(kind="ask_user")
# ─────────────────────────────────────────────

def _ask_user_block(
    tool_id: str = "toolu_ask",
    header: str = "Approach",
    question: str = "Which fix?",
) -> dict:
    return {
        "type": "tool_use",
        "id": tool_id,
        "name": "AskUserQuestion",
        "input": {
            "questions": [{
                "header": header,
                "question": question,
                "options": [
                    {"label": "A", "description": "First"},
                    {"label": "B", "description": "Second"},
                ],
                "multiSelect": False,
            }],
        },
    }


@pytest.mark.asyncio
async def test_ask_user_question_emits_permission_request():
    q: asyncio.Queue = asyncio.Queue()
    event = _assistant_event([_ask_user_block()])
    await session_reader.dispatch_event("sess", event, q, is_first_message=False)
    frames = await _drain(q)
    perm = [f for f in frames if isinstance(f, PermissionRequest)]
    assert len(perm) == 1
    assert perm[0].kind == "ask_user"
    assert perm[0].questions is not None
    assert perm[0].questions[0]["header"] == "Approach"


@pytest.mark.asyncio
async def test_inline_tool_denial_emits_tool_blocked():
    q: asyncio.Queue = asyncio.Queue()
    import devscope_bridge._live_feed_helpers as _lfh
    _lfh.register_pending_tool_calls("sess", [{
        "type": "tool_use",
        "id": "tid-bash",
        "name": "Bash",
        "input": {"command": "echo hi"},
    }])
    user_ev = {
        "type": "user",
        "message": {
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": "tid-bash",
                "is_error": True,
                "content": "blocked by sandbox",
            }],
        },
    }
    await session_reader.dispatch_event("sess", user_ev, q, is_first_message=False)
    frames = await _drain(q)
    blocked = [f for f in frames if isinstance(f, PermissionRequest) and f.kind == "tool_blocked"]
    assert len(blocked) == 1
    assert blocked[0].tool_name == "Bash"


@pytest.mark.asyncio
async def test_result_event_emits_turn_state_false():
    q: asyncio.Queue = asyncio.Queue()
    await session_reader.dispatch_event("sess", _result_event(), q, is_first_message=False)
    frames = await _drain(q)
    turn_frames = [f for f in frames if isinstance(f, TurnState)]
    assert len(turn_frames) == 1
    assert turn_frames[0].running is False


@pytest.mark.asyncio
async def test_ask_user_denial_not_re_emitted():
    """AskUserQuestion in permission_denials is suppressed — it is already
    surfaced as an actionable kind="ask_user" card, so the redundant scary
    "Permission denied: AskUserQuestion" notice must NOT be emitted."""
    q: asyncio.Queue = asyncio.Queue()
    result_ev = _result_event(permission_denials=[{
        "tool_name": "AskUserQuestion",
        "tool_use_id": "toolu_ask",
        "tool_input": {"questions": []},
    }])

    await session_reader.dispatch_event("sess", result_ev, q, is_first_message=False)
    frames = await _drain(q)

    denied = [
        f for f in frames
        if isinstance(f, PermissionRequest) and f.kind == "permission_denied"
    ]
    assert len(denied) == 0, f"AskUserQuestion denial should be suppressed: {denied}"
    assert any(isinstance(f, AiDone) for f in frames)


@pytest.mark.asyncio
async def test_run_prompt_includes_image_content_block():
    """An image attachment in the context is sent as a real Claude image
    content block, placed before the text block."""
    from devscope_bridge.models import MessageContext, PageAttachment

    proc = _make_fake_proc()

    async def fake_spawn(*args, **kwargs):
        return proc

    ctx = MessageContext(attachments=[
        PageAttachment(
            kind="image", label="paste.png",
            data="data:image/png;base64,iVBORw0KGgo=",
        ),
    ])
    with patch("devscope_bridge.session_manager.asyncio.create_subprocess_exec",
               side_effect=fake_spawn):
        await mgr.run_prompt("img-sess", "what is this?", context=ctx)

    payload = json.loads(proc.stdin.write.call_args_list[-1][0][0].decode().strip())
    content = payload["message"]["content"]

    image_blocks = [b for b in content if b.get("type") == "image"]
    assert len(image_blocks) == 1, f"Expected 1 image block, got: {content}"
    assert image_blocks[0]["source"]["media_type"] == "image/png"
    assert image_blocks[0]["source"]["data"] == "iVBORw0KGgo="
    # Image precedes the text block (Anthropic's recommended ordering).
    assert content[0]["type"] == "image"
    assert any(b.get("type") == "text" for b in content)


@pytest.mark.asyncio
async def test_send_approval_ask_user_writes_answers():
    proc = _make_fake_proc()

    async def fake_spawn(*args, **kwargs):
        return proc

    with patch("devscope_bridge.session_manager.asyncio.create_subprocess_exec",
               side_effect=fake_spawn):
        await mgr.run_prompt("ask-sess", "question me")

    request_id = "req-ask-1"
    session_reader._pending_permissions[request_id] = {
        "session": "ask-sess",
        "kind": "ask_user",
        "questions": [],
    }
    result = await mgr.send_approval(
        "ask-sess", request_id, "submit",
        answers={"Approach": "A"},
        custom_text="note",
    )
    assert result is True
    payload = json.loads(proc.stdin.write.call_args_list[-1][0][0].decode().strip())
    text = payload["message"]["content"][0]["text"]
    assert "Approach" in text
    assert "A" in text
    assert "note" in text
