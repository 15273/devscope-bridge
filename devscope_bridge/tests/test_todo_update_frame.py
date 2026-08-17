"""
test_todo_update_frame.py

dispatch_event's assistant branch emits a TodoUpdate frame (in addition to
the normal AgentActivity row) when it sees a TodoWrite tool_use block.

Some CLI sessions don't expose TodoWrite at all — the model uses
TaskCreate{subject, description, activeForm?} + TaskUpdate{taskId, status}
instead. dispatch_event also accumulates those into the same TodoUpdate
frame shape (see `_process_task_blocks` / `_task_lists` in session_reader.py)
so the panel is unaffected by which tool the CLI actually offered.

1. Assistant event with a TodoWrite tool_use block → TodoUpdate frame
   emitted with todos + turn_id.
2. A non-TodoWrite assistant event emits no TodoUpdate frame.
3. TaskCreate → TodoUpdate with one pending item (content=subject,
   activeForm respected).
4. TaskCreate + TaskCreate then TaskUpdate(taskId "1", completed) →
   TodoUpdate items [completed, pending], ordered by taskId.
5. TaskUpdate for an unknown taskId → stub entry, no crash.
"""

import asyncio
import pytest

from devscope_bridge import session_reader
from devscope_bridge.models import AgentActivity, TodoUpdate


async def _drain(q: asyncio.Queue) -> list:
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


def _last_todo_update(frames: list) -> TodoUpdate | None:
    updates = [f for f in frames if isinstance(f, TodoUpdate)]
    return updates[-1] if updates else None


def _assistant_event(content: list) -> dict:
    return {"type": "assistant", "message": {"role": "assistant", "content": content}}


def _todo_write_block(todos: list[dict], tool_id: str = "toolu_todo") -> dict:
    return {"type": "tool_use", "id": tool_id, "name": "TodoWrite", "input": {"todos": todos}}


def _bash_block(tool_id: str = "toolu_bash", command: str = "ls") -> dict:
    return {"type": "tool_use", "id": tool_id, "name": "Bash", "input": {"command": command}}


def _task_create_block(subject: str, tool_id: str = "toolu_taskcreate", active_form: str | None = None) -> dict:
    inp = {"subject": subject, "description": subject}
    if active_form is not None:
        inp["activeForm"] = active_form
    return {"type": "tool_use", "id": tool_id, "name": "TaskCreate", "input": inp}


def _task_update_block(task_id: str, status: str, tool_id: str = "toolu_taskupdate") -> dict:
    return {
        "type": "tool_use", "id": tool_id, "name": "TaskUpdate",
        "input": {"taskId": task_id, "status": status},
    }


@pytest.mark.asyncio
async def test_todo_write_emits_todo_update_frame():
    session_reader.set_current_turn_id("s-todo", "turn-todo-1")
    q = asyncio.Queue()
    todos = [
        {"content": "Write test", "status": "completed", "activeForm": "Writing test"},
        {"content": "Implement", "status": "in_progress", "activeForm": "Implementing"},
        {"content": "Verify", "status": "pending", "activeForm": "Verifying"},
    ]
    await session_reader.dispatch_event(
        "s-todo", _assistant_event([_todo_write_block(todos)]), q, is_first_message=False,
    )
    frames = await _drain(q)

    todo_update = next((f for f in frames if isinstance(f, TodoUpdate)), None)
    assert todo_update is not None
    assert todo_update.turn_id == "turn-todo-1"
    assert todo_update.todos == todos

    # Still emits the normal AgentActivity row alongside it.
    activity = next((f for f in frames if isinstance(f, AgentActivity)), None)
    assert activity is not None
    assert activity.tool == "TodoWrite"


@pytest.mark.asyncio
async def test_non_todo_write_assistant_event_emits_no_todo_update():
    session_reader.set_current_turn_id("s-no-todo", "turn-no-todo-1")
    q = asyncio.Queue()
    await session_reader.dispatch_event(
        "s-no-todo", _assistant_event([_bash_block()]), q, is_first_message=False,
    )
    frames = await _drain(q)

    assert not any(isinstance(f, TodoUpdate) for f in frames)


@pytest.mark.asyncio
async def test_task_create_emits_todo_update_with_pending_item():
    session_reader.set_current_turn_id("s-task-create", "turn-task-create-1")
    q = asyncio.Queue()
    await session_reader.dispatch_event(
        "s-task-create",
        _assistant_event([_task_create_block("Write the report", active_form="Writing the report")]),
        q, is_first_message=False,
    )
    frames = await _drain(q)

    todo_update = _last_todo_update(frames)
    assert todo_update is not None
    assert todo_update.turn_id == "turn-task-create-1"
    assert todo_update.todos == [
        {"content": "Write the report", "status": "pending", "activeForm": "Writing the report"},
    ]


@pytest.mark.asyncio
async def test_task_create_twice_then_update_orders_by_task_id():
    session = "s-task-sequence"
    session_reader.set_current_turn_id(session, "turn-seq-1")
    q = asyncio.Queue()

    await session_reader.dispatch_event(
        session, _assistant_event([_task_create_block("First task")]), q, is_first_message=False,
    )
    await session_reader.dispatch_event(
        session, _assistant_event([_task_create_block("Second task")]), q, is_first_message=False,
    )
    await session_reader.dispatch_event(
        session, _assistant_event([_task_update_block("1", "completed")]), q, is_first_message=False,
    )
    frames = await _drain(q)

    todo_update = _last_todo_update(frames)
    assert todo_update is not None
    assert [t["status"] for t in todo_update.todos] == ["completed", "pending"]
    assert todo_update.todos[0]["content"] == "First task"
    assert todo_update.todos[1]["content"] == "Second task"


@pytest.mark.asyncio
async def test_task_update_unknown_task_id_creates_stub_without_crashing():
    session = "s-task-unknown"
    session_reader.set_current_turn_id(session, "turn-unknown-1")
    q = asyncio.Queue()

    await session_reader.dispatch_event(
        session, _assistant_event([_task_update_block("99", "in_progress")]), q, is_first_message=False,
    )
    frames = await _drain(q)

    todo_update = _last_todo_update(frames)
    assert todo_update is not None
    assert todo_update.todos == [
        {"content": "Task 99", "status": "in_progress", "activeForm": "Task 99"},
    ]
