"""
models.py — Pydantic v2 models for WebSocket frames and REST responses.
"""

from typing import Any, Literal
from pydantic import BaseModel, Field


# ─────────────────────────────────────────────
# Extension → Bridge frames
# ─────────────────────────────────────────────

class ElementContext(BaseModel):
    """A page element attached as context (from the extension's element picker)."""
    selector: str
    tag: str
    text: str | None = None
    ariaRole: str | None = None
    ariaName: str | None = None
    href: str | None = None
    outerHTML: str | None = None
    boundingBox: dict[str, Any] | None = None
    inViewport: bool | None = None
    cssSnapshot: dict[str, str] | None = None
    domChain: list[str] | None = None   # ancestor selector chain, outermost→innermost
    editRef: str | None = None          # data-edit-ref anchor for stable re-location
    screenshotSnippet: str | None = None  # cropped JPEG data URL of the element
    frameUrl: str | None = None
    note: str | None = None             # the user's annotation: what to change


class PageAttachment(BaseModel):
    """A captured slice of page state attached as context."""
    kind: str
    label: str
    url: str | None = None
    data: Any | None = None


class BoundTabContext(BaseModel):
    """Session-bound browser tab from the DevScope panel."""
    tabId: int
    url: str
    title: str
    windowId: int


class MessageContext(BaseModel):
    elements: list[ElementContext] = Field(default_factory=list)
    attachments: list[PageAttachment] = Field(default_factory=list)
    boundTab: BoundTabContext | None = None


class UserMsg(BaseModel):
    type: str = "user_msg"
    agent: str = "claude"
    text: str
    context: MessageContext | None = None
    mode: str | None = None
    model: str | None = None
    coach_enabled: bool = False
    coach_lang: str = "he"
    coach_focus: list[str] = Field(default_factory=list)
    # Cross-workstream contract 1 (frame ack): when present, the bridge replies
    # with msg_ack on the same WS immediately after writing to stdin/enqueuing.
    # Optional so old panel builds without this field keep working unacked.
    client_msg_id: str | None = None


class BrowserResult(BaseModel):
    """Result frame sent from the Chrome extension back to the bridge."""
    type: str = "browser_result"
    action_id: str
    ok: bool
    data: Any | None = None
    error: str | None = None


# ─────────────────────────────────────────────
# Bridge → Extension frames
# ─────────────────────────────────────────────

class ToolCall(BaseModel):
    """Sent from bridge to the Chrome extension to request a browser action."""
    type: str = "tool_call"
    action_id: str
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    session: str = "default"
    quiet: bool = False


class SessionReady(BaseModel):
    type: str = "session_ready"
    session: str
    session_id: str
    resumed: bool


class AiChunk(BaseModel):
    type: str = "ai_chunk"
    session: str
    text: str
    turn_id: str | None = None      # stable per user turn
    block_index: int = 0            # content_block index within the turn


class ThinkingChunk(BaseModel):
    """Streamed extended-thinking text (rendered dim/collapsible in the panel)."""
    type: str = "thinking_chunk"
    session: str
    text: str
    turn_id: str | None = None


class AiDone(BaseModel):
    type: str = "ai_done"
    session: str
    exit_code: int = 0
    turn_id: str | None = None


class AiError(BaseModel):
    type: str = "ai_error"
    session: str
    exit_code: int
    stderr_tail: str


class RateLimit(BaseModel):
    type: str = "rate_limit"
    session: str
    retry_ms: int


class AgentActivity(BaseModel):
    """What the agent is doing right now (parsed from tool_use events)."""
    type: str = "agent_activity"
    session: str
    label: str
    tool: str | None = None
    detail: str | None = None
    # Correlates a "running" activity with its later "done"/"error" activity —
    # both are populated with the same Claude tool_use content-block id, so
    # the frontend can render one row that transitions in place instead of
    # two disconnected messages.
    call_id: str | None = None
    # One of "running" | "done" | "error" | None (None = not a tool call,
    # e.g. the "Thinking" / "still working…" ambient activities).
    status: str | None = None
    turn_id: str | None = None


class TodoUpdate(BaseModel):
    """Live todo-list state parsed from a TodoWrite tool_use block."""
    type: str = "todo_update"
    session: str
    turn_id: str | None = None
    todos: list[dict[str, str]] = Field(default_factory=list)  # {content, status, activeForm}


class Usage(BaseModel):
    """Per-turn token + cost usage, emitted at end-of-turn (result event)."""
    type: str = "usage"
    session: str
    tokens: int = 0
    cost_usd: float = 0.0
    duration_ms: int = 0
    input_tokens: int = 0   # current context window occupancy (this turn's input)


class TurnResult(BaseModel):
    """Per-turn footer data, emitted at the CLI `result` event before AiDone."""
    type: str = "turn_result"
    session: str
    turn_id: str | None = None
    duration_ms: int = 0
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    model: str | None = None


class AskStart(BaseModel):
    """A parallel side-query (`/ask`) or Cursor scout (`/cursor-ctx`) began.

    Side-queries run in their own short-lived process alongside the main turn;
    the panel renders them in a distinct (dashed) bubble keyed by question_id so
    their answer is never confused with the main turn's stream.
    """
    type: str = "ask_start"
    session: str
    question_id: str
    question: str
    kind: Literal["ask", "cursor_ctx", "cursor_task", "english_coach"] = "ask"


class AskChunk(BaseModel):
    """Streamed text for a parallel side-query, keyed to its question_id."""
    type: str = "ask_chunk"
    session: str
    question_id: str
    text: str


class AskDone(BaseModel):
    """A parallel side-query finished (ok) or failed/timed out (ok=False)."""
    type: str = "ask_done"
    session: str
    question_id: str
    ok: bool = True


class ContextRecovery(BaseModel):
    """Emitted once when a respawned session's next turn is given a recovery
    preamble rebuilt from its transcript.

    After a forced respawn (hung process) the new process starts a FRESH CLI
    conversation (no --resume, which would replay the interrupted turn and hang).
    To keep the agent from forgetting everything, the bridge injects a compact
    summary of the prior conversation (first request + latest progress) into the
    next user message.  This frame lets the panel show an honest "context
    recovered" status instead of falsely claiming "history kept".
    """
    type: str = "context_recovery"
    session: str
    recovered: bool = True
    detail: str | None = None


class WatchdogReport(BaseModel):
    """Emitted by the Watchdog Medic — a SEPARATE diagnostic agent the bridge
    spawns when a session goes silent mid-turn and looks stuck.

    The medic investigates why the turn is stuck, streams its findings to the
    panel, and may apply a scoped code fix (devscope_bridge/ + the extension
    dir only).  It runs as its own claude --print process and never touches the
    stuck process directly.

    Phases
    ------
    - "start" : medic spawned; ``diagnostics`` carries the captured state bundle.
    - "chunk" : a streamed slice of the medic's findings (``text``).
    - "done"  : medic finished; ``detail`` is a one-line outcome summary.
    - "error" : medic could not run / timed out; ``detail`` explains why.

    The medic ALSO streams its prose to the panel via ordinary AiChunk frames so
    it is visible in the existing UI without any extension change; WatchdogReport
    is the structured signal for clients that want a dedicated medic card.
    """
    type: str = "watchdog_report"
    session: str
    phase: Literal["start", "chunk", "done", "error"]
    text: str | None = None
    detail: str | None = None
    diagnostics: dict[str, Any] | None = None   # non-None only on phase="start"


class PermissionOption(BaseModel):
    """A single choice the user can pick in response to a PermissionRequest."""
    id: str
    label: str


class PermissionRequest(BaseModel):
    """Emitted when claude needs explicit approval before proceeding.

    Kinds
    -----
    - "plan" : plan mode — ExitPlanMode; approve → "yes proceed" user turn.
    - "ask_user" : AskUserQuestion tool; user picks options → formatted reply turn.
    - "tool_blocked" : a tool was denied by the sandbox; allow_once respawns with
      bypass permissions and retries, skip is a no-op.
    - "permission_denied" : informational only (legacy aggregated denials).
    """
    type: str = "permission_request"
    session: str
    request_id: str
    kind: Literal["plan", "permission_denied", "ask_user", "tool_blocked"]
    title: str
    description: str
    options: list[PermissionOption] = Field(default_factory=list)
    plan_file_path: str | None = None   # non-None only for kind="plan"
    questions: list[dict[str, Any]] | None = None  # AskUserQuestion payload
    tool_name: str | None = None
    tool_input: dict[str, Any] | None = None


class TurnState(BaseModel):
    """Push notification when a session turn starts or ends (for live UI sync)."""
    type: str = "turn_state"
    session: str
    running: bool
    turn_id: str | None = None


class PermissionResponse(BaseModel):
    """Inbound WS frame from the UI to approve or deny a permission request."""
    type: str = "permission_response"
    request_id: str
    option_id: str  # "approve" | "deny" | "allow_once" | "skip" | "submit"
    answers: dict[str, Any] | None = None  # ask_user: header → label or [labels]
    custom_text: str | None = None  # ask_user: free-text "Other" reply


class MsgAck(BaseModel):
    """Contract 1: confirms a user_msg was written to stdin / enqueued.

    Only sent when the inbound user_msg carried a client_msg_id — old panel
    builds without it never receive this frame and keep working as before.
    """
    type: str = "msg_ack"
    client_msg_id: str


class PermAck(BaseModel):
    """Contract 1: confirms a permission_response was forwarded to the session."""
    type: str = "perm_ack"
    request_id: str


# ─────────────────────────────────────────────
# REST response helpers + orchestrator frames
# ─────────────────────────────────────────────
# Split into models_rest.py (this module was approaching the 400-line file-size
# limit) and re-exported here so existing `from devscope_bridge.models import
# SessionInfo` (etc.) call sites across the codebase are unaffected.

from devscope_bridge.models_rest import (  # noqa: E402,F401
    ApprovalRequest,
    EmployeeNote,
    HealthResponse,
    OpenPathRequest,
    SessionCoach,
    SessionCreateRequest,
    SessionInfo,
    SessionsResponse,
    SlashCommandCard,
    SubAgent,
    TaskDigest,
    TaskUpdate,
)
