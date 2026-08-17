/**
 * frames.ts — TypeScript mirrors of devscope_bridge/models.py
 *
 * Extension → Bridge
 */
export type Agent = 'claude' | 'cursor';

/** Operational mode — maps to claude/cursor CLI flags + system-prompt presets. */
export type AgentMode = 'act' | 'plan' | 'inspect' | 'test';

/** A page element the user attached as context (from the element picker). */
export interface ElementContext {
  selector: string;
  tag: string;
  text?: string;
  ariaRole?: string | null;
  ariaName?: string | null;
  href?: string | null;
  outerHTML?: string;
  boundingBox?: { x: number; y: number; width: number; height: number };
  inViewport?: boolean;
  cssSnapshot?: Record<string, string>;
  /** Ancestor selector chain (outermost→innermost), e.g. ["div.ask","span.label"]. */
  domChain?: string[];
  /** Stable anchor stamped on the element (data-edit-ref) so the agent can re-find it. */
  editRef?: string;
  /** Cropped JPEG thumbnail of the element (data URL). */
  screenshotSnippet?: string;
  /** Frame URL where the element was picked. */
  frameUrl?: string;
  /** The user's annotation for this element — what they want changed. */
  note?: string;
}

export type PageAttachmentKind =
  | 'screenshot'
  | 'snapshot'
  | 'console'
  | 'network'
  | 'page_info'
  | 'image';

/**
 * A captured slice of page state the user attached as context.
 *
 * For kind="image" the `data` field is a base64 data URL
 * ("data:image/png;base64,…"); the bridge turns it into a real Claude image
 * content block so the agent actually sees the picture.
 */
export interface PageAttachment {
  kind: PageAttachmentKind;
  label: string;
  url?: string;
  data: unknown;
}

/** Session-bound browser tab — injected so the agent targets the right window/tab. */
export interface BoundTabContext {
  tabId: number;
  url: string;
  title: string;
  windowId: number;
}

/** Structured context attached to a user message. */
export interface MessageContext {
  elements?: ElementContext[];
  attachments?: PageAttachment[];
  boundTab?: BoundTabContext;
}

export interface UserMsg {
  type: 'user_msg';
  agent: Agent;
  text: string;
  context?: MessageContext;
  mode?: AgentMode;
  model?: string;
  /** English coach — send flat (not nested) per bridge contract. */
  coach_enabled?: boolean;
  coach_lang?: string;
  coach_focus?: string[];
  /**
   * Panel-generated id echoed back by the bridge in a `msg_ack` frame
   * (chat-reliability contract 1). Also used for offscreen send-dedupe.
   */
  client_msg_id?: string;
}

/** Bridge → Extension: the bridge accepted a user_msg (contract 1). */
export interface MsgAck {
  type: 'msg_ack';
  session?: string;
  client_msg_id: string;
}

/** Bridge → Extension: the bridge accepted a permission_response (contract 1). */
export interface PermAck {
  type: 'perm_ack';
  session?: string;
  request_id: string;
}

export interface BrowserResult {
  type: 'browser_result';
  action_id: string;
  ok: boolean;
  data?: unknown;
  error?: string;
}

/** Bridge → Extension: request a browser action via MCP tool_call. */
export interface ToolCall {
  type: 'tool_call';
  action_id: string;
  tool: string;
  args: Record<string, unknown>;
  session: string;
  /** When true, offscreen executes the tool but does not surface rows in chat. */
  quiet?: boolean;
}

/**
 * Bridge → Extension
 */
export interface SessionReady {
  type: 'session_ready';
  session: string;
  session_id: string;
  resumed: boolean;
}

export interface AiChunk {
  type: 'ai_chunk';
  session: string;
  text: string;
  turn_id?: string | null;
  block_index?: number;
}

/** Bridge → Extension: a streamed extended-thinking token delta (separate from ai_chunk text). */
export interface ThinkingChunk {
  type: 'thinking_chunk';
  session: string;
  text: string;
  turn_id?: string | null;
}

/** Bridge → Extension: per-turn cost/latency summary, emitted once a turn completes. */
export interface TurnResult {
  type: 'turn_result';
  session: string;
  turn_id?: string | null;
  duration_ms: number;
  cost_usd: number;
  input_tokens: number;
  output_tokens: number;
  model?: string | null;
}

export interface AiDone {
  type: 'ai_done';
  session: string;
  exit_code: number;
  turn_id?: string | null;
}

export interface AiError {
  type: 'ai_error';
  session: string;
  exit_code: number;
  stderr_tail: string;
}

export interface RateLimit {
  type: 'rate_limit';
  session: string;
  retry_ms: number;
}

export interface AgentActivity {
  type: 'agent_activity';
  session: string;
  label: string;
  tool?: string | null;
  detail?: string | null;
  /**
   * Correlates a "running" activity with its later "done"/"error" activity for
   * the same tool call — both carry the same Claude tool_use content-block id,
   * letting the frontend render one row that transitions in place.
   */
  call_id?: string | null;
  /** 'running' | 'done' | 'error' | null — null = ambient activity (e.g. "Thinking…"), not a tool-call lifecycle event. */
  status?: 'running' | 'done' | 'error' | null;
  turn_id?: string | null;
}

/** A single todo item as sent by the agent's TodoWrite tool call. */
export interface TodoItem {
  content: string;
  status: 'pending' | 'in_progress' | 'completed' | string;
  activeForm: string;
}

/** Bridge → Extension: live todo-list state parsed from a TodoWrite tool_use block. */
export interface TodoUpdate {
  type: 'todo_update';
  session: string;
  turn_id?: string | null;
  todos: TodoItem[];
}

export interface Usage {
  type: 'usage';
  session: string;
  tokens: number;
  cost_usd: number;
  duration_ms: number;
  input_tokens: number;
}

export interface PermissionOption {
  id: string;
  label: string;
}

/** Bridge → Extension: claude needs approval, questions, or a blocked tool retry. */
export interface AskUserQuestionItem {
  question: string;
  header: string;
  options: { label: string; description?: string }[];
  multiSelect?: boolean;
}

export interface PermissionRequest {
  type: 'permission_request';
  session: string;
  request_id: string;
  kind: 'plan' | 'permission_denied' | 'ask_user' | 'tool_blocked';
  title: string;
  description: string;
  options: PermissionOption[];
  plan_file_path?: string | null;
  questions?: AskUserQuestionItem[] | null;
  tool_name?: string | null;
  tool_input?: Record<string, unknown> | null;
}

/** Push notification when a turn starts or ends (live UI sync). */
export interface TurnState {
  type: 'turn_state';
  session: string;
  running: boolean;
  turn_id?: string | null;
}

/** Extension → Bridge: the user's decision on a PermissionRequest. */
export interface PermissionResponse {
  type: 'permission_response';
  request_id: string;
  option_id: string;
  answers?: Record<string, string | string[]> | null;
  custom_text?: string | null;
}

/** Bridge → Extension: a sub-agent (Task tool) lifecycle event. */
export interface SubAgent {
  type: 'sub_agent';
  session: string;
  agent_id: string;
  name: string;
  description: string;
  phase: 'start' | 'activity' | 'done';
  ok?: boolean | null;
  result?: string | null;
  activity?: string | null;
}

/** Bridge → Extension: MEDIC watchdog lifecycle frame. */
export interface WatchdogReport {
  type: 'watchdog_report';
  session: string;
  phase: 'start' | 'chunk' | 'done' | 'error';
  text?: string;
  detail?: string;
  diagnostics?: Record<string, unknown>;
}

/** Bridge → Extension: session context was recovered from transcript on respawn. */
export interface ContextRecovery {
  type: 'context_recovery';
  session: string;
  recovered: boolean;
  detail?: string;
}

/** Bridge → Extension: a parallel /ask or /cursor-ctx side-query started. */
export interface AskStart {
  type: 'ask_start';
  session: string;
  question_id: string;
  question: string;
  kind?: 'ask' | 'cursor_ctx' | 'cursor_task' | 'english_coach';
}

/** Bridge → Extension: a streaming chunk for an in-flight /ask side-query. */
export interface AskChunk {
  type: 'ask_chunk';
  session: string;
  question_id: string;
  text: string;
}

/** Bridge → Extension: a parallel /ask side-query completed. */
export interface AskDone {
  type: 'ask_done';
  session: string;
  question_id: string;
  ok: boolean;
}

/**
 * Bridge → Extension: result of a bridge-side builtin slash command.
 *
 * Rendered as a native info card in the chat panel.
 * kind="usage"   — token usage breakdown  (data has full breakdown dict)
 * kind="model"   — model switch confirmation (data has {model: string})
 * kind="memory"  — memory/context listing (data has {files: [{label,path}]})
 * kind="new"     — new conversation started
 * kind="compact" — conversation compacted
 */
export interface SlashCommandCard {
  type: 'slash_command_card';
  session: string;
  kind: 'usage' | 'model' | 'memory' | 'new' | 'compact';
  title: string;
  body: string;
  data: Record<string, unknown>;
}

export interface SessionCoach {
  type: 'session_coach';
  session: string;
  level: 'info' | 'warn' | 'action';
  title: string;
  body?: string;
  suggested_model?: string | null;
  current_model?: string | null;
  auto_action?: 'none' | 'compact';
  metrics?: Record<string, unknown>;
}

export type BridgeInbound =
  | SessionReady
  | AiChunk
  | ThinkingChunk
  | TurnResult
  | AiDone
  | AiError
  | RateLimit
  | AgentActivity
  | Usage
  | TodoUpdate
  | PermissionRequest
  | TurnState
  | SubAgent
  | ToolCall
  | WatchdogReport
  | ContextRecovery
  | AskStart
  | AskChunk
  | AskDone
  | SlashCommandCard
  | SessionCoach
  | MsgAck
  | PermAck;

export type BridgeOutbound = UserMsg | BrowserResult | PermissionResponse;

/**
 * REST API — shape returned by GET /sessions
 * (backend agent in parallel extends this with agent + cwd)
 */
export interface SessionInfo {
  session_id: string;
  created_at: string;
  last_used: string;
  active: boolean;
  /** True while the bridge is waiting for a result event from the subprocess. */
  turn_running?: boolean;
  agent?: Agent;
  cwd?: string;
  mode?: AgentMode;
  model?: string;
  /** Claude Code subagent slug (claude --agent) */
  claude_agent?: string | null;
  /** chat = user session; worker/manager/orchestrator = autonomous agents */
  purpose?: string;
  // ── Liveness fields (chat-reliability contract 2). All optional: they are
  // ABSENT on bridges that predate the reliability overhaul — consumers must
  // feature-detect and never assume presence.
  /** Epoch SECONDS of the last stdout/frame output from the agent, or null. */
  last_output_at?: number | null;
  /** Name of the tool currently executing, or null when idle/between tools. */
  current_tool?: string | null;
  /** Seconds since the in-flight turn started, or null when idle. */
  turn_elapsed_s?: number | null;
  /** Steering prompts queued behind the in-flight turn. */
  queued_turns?: number;
  /** Kind of pending interactive request ("plan" / "ask_user" / "tool_blocked"), or null. */
  awaiting?: string | null;
}

/** Shape of GET /sessions/{name}/pending (chat-reliability contract 3). */
export interface PendingRequestsResponse {
  pending: PermissionRequest[];
}

export interface CreateSessionPayload {
  name: string;
  agent: Agent;
  cwd: string;
  mode?: AgentMode;
  model?: string;
  claude_agent?: string | null;
  purpose?: string;
}
