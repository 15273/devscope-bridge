"""
models_rest.py — REST response models + orchestrator WS frames.

Split out of models.py (which was approaching the 400-line file-size limit)
so the WS chat-frame models stay in one focused file. Re-exported from
models.py so existing `from devscope_bridge.models import SessionInfo`
imports across the codebase are unaffected.
"""

from typing import Any, Literal
from pydantic import BaseModel, Field


class SessionInfo(BaseModel):
    session_id: str
    created_at: str
    last_used: str
    active: bool
    turn_running: bool = False
    agent: str | None = None
    cwd: str | None = None
    mode: str | None = None
    model: str | None = None
    claude_agent: str | None = None
    purpose: str | None = "chat"
    # Cross-workstream contract 2 (liveness fields). All optional/defaulted so
    # old panel builds parsing this response are unaffected. Claude sessions
    # populate these from session_reader/session_manager; Cursor sessions
    # populate them from session_manager_cursor.get_session_state() by the
    # same key names (WS-A just reads whatever is present, via .get()).
    last_output_at: float | None = None       # epoch seconds of last stdout activity
    current_tool: str | None = None           # tool currently running, if any
    turn_elapsed_s: float | None = None        # seconds into the current turn
    queued_turns: int = 0                      # steering messages waiting on a new turn
    awaiting: str | None = None                # "plan" | "ask_user" | "tool_blocked" | None


class SessionCreateRequest(BaseModel):
    name: str
    agent: str
    cwd: str
    mode: str | None = None
    model: str | None = None
    claude_agent: str | None = None
    purpose: str | None = "chat"


class OpenPathRequest(BaseModel):
    """Request to open a local file/folder with the OS default handler."""
    path: str


class SessionsResponse(BaseModel):
    sessions: dict[str, SessionInfo] = Field(default_factory=dict)


class SubAgent(BaseModel):
    """Lifecycle frame for a sub-agent spawned via the Task tool.

    Emitted three times per sub-agent invocation:

    phase="start"
        Emitted when the parent's ``assistant`` event contains a Task tool_use
        block.  ``agent_id`` is the tool_use ``id`` (e.g. ``toolu_xxx``).
        ``name`` is ``input.subagent_type`` if present, otherwise ``"sub-agent"``.
        ``description`` is ``input.description`` or ``input.prompt`` (first 200 chars).

    phase="activity"
        Emitted when a top-level tool activity (AgentActivity) fires while one
        or more Task tool_use blocks are still open (i.e. sub-agents are in
        flight).  ``agent_id`` identifies the most-recently-spawned in-flight
        sub-agent.  ``activity`` is the human label of the tool being run.
        NOTE: In the CLI stream-json path the parent stream does NOT forward
        the sub-agent's internal tool calls — these are synthesised from the
        top-level stream's ambient tool activity while a Task is open, so they
        are an approximation.  ``parent_tool_use_id`` is not available in the
        CLI path; full per-child-step linkage requires the Agent SDK or hooks.

    phase="done"
        Emitted when the ``user`` event carrying a ``tool_result`` for the Task
        tool_use_id arrives.  ``ok`` is True unless ``tool_result.is_error`` is
        True.  ``result`` is the first 200 chars of the tool_result content.

    Frontend tree contract
    ----------------------
    The UI maintains a dict keyed by ``agent_id``.  On ``phase="start"`` it
    inserts a new row (spinning).  On ``phase="activity"`` it updates the row's
    live-activity text.  On ``phase="done"`` it marks the row as complete.
    Multiple parallel sub-agents are distinguished by their distinct
    ``agent_id`` values (each Task tool_use has a unique ``id``).
    """
    type: str = "sub_agent"
    session: str
    agent_id: str          # Task tool_use id — stable key for the whole lifecycle
    name: str              # subagent_type or "sub-agent"
    description: str       # truncated prompt/description
    phase: Literal["start", "activity", "done"]
    ok: bool | None = None          # non-None only for phase="done"
    result: str | None = None       # non-None only for phase="done"
    activity: str | None = None     # non-None only for phase="activity"


class SessionCoach(BaseModel):
    """Token-efficiency coaching hint or post auto-compact notice for user chat sessions."""
    type: str = "session_coach"
    session: str
    level: Literal["info", "warn", "action"] = "warn"
    title: str
    body: str = ""
    suggested_model: str | None = None
    current_model: str | None = None
    auto_action: Literal["none", "compact"] = "none"
    metrics: dict[str, Any] = Field(default_factory=dict)


class SlashCommandCard(BaseModel):
    """Emitted by bridge builtin slash-command handlers (/usage, /model, /memory, etc.).

    The extension renders this as a distinct, styled info card in the chat panel.

    kind values
    -----------
    "usage"   : Token-usage report.  ``data`` contains token and cost breakdown.
    "model"   : Model-switch confirmation.  ``data`` contains {"model": "<name>"}.
    "memory"  : Memory/context listing.    ``data`` contains {"files": [...]}.
    "new"     : Fresh session started.     ``data`` is {}.
    "compact" : Compact/summarise done.    ``data`` is {}.
    "status"  : Session/CLI status info.   ``data`` is {}.
    "add_dir" : Extra working-dir added.   ``data`` contains {"path": ..., "valid": bool}.
    """
    type: str = "slash_command_card"
    session: str
    kind: Literal["usage", "model", "memory", "new", "compact", "status", "add_dir"]
    title: str
    body: str = ""
    data: dict[str, Any] = Field(default_factory=dict)


class HealthResponse(BaseModel):
    ok: bool = True
    version: str = "0.1"
    uptime_s: int


# ─────────────────────────────────────────────
# Orchestrator WS frames (Plans 2–3)
# ─────────────────────────────────────────────

class TaskDigest(BaseModel):
    """Periodic board summary pushed to the panel after each orchestrator tick."""
    type: str = "task_digest"
    summary: str
    counts: dict[str, int] = {}          # status -> count
    report: str | None = None            # MoM-drafted user-facing report


class TaskUpdate(BaseModel):
    """A single task's status change, pushed live to the panel."""
    type: str = "task_update"
    task_id: str
    title: str
    status: str
    domain: str | None = None
    note: str | None = None


class ApprovalRequest(BaseModel):
    """A sensitive action awaiting the user's approval."""
    type: str = "approval_request"
    task_id: str
    title: str
    action: str
    payload: dict = {}
    approval_id: int | None = None


class EmployeeNote(BaseModel):
    """Proactive note from the Autonomous Employee (question/blocker/milestone/digest)."""
    type: str = "employee_note"
    kind: Literal["question", "blocker", "milestone_done", "project_done", "daily_digest"]
    title: str
    body: str = ""
    task_id: str | None = None
