/**
 * sessionTypes.ts — store types and initial state.
 *
 * Split out of sessionStore.ts so reducers/helpers can type-import without
 * a runtime cycle. sessionStore.ts re-exports everything public.
 */
import type { Agent, AgentActivity, AskUserQuestionItem, SessionInfo, MessageContext, TodoItem } from '@/shared/frames';
import type { BoundTab, BrowserTabSummary } from '@/shared/tabBinding';
import type { ReliabilityAction } from './reliabilityActions';
import type { TurnMeta, TurnSegment } from './turnSegments';

export type Role = 'user' | 'assistant' | 'tool' | 'permission' | 'medic' | 'ask' | 'status' | 'slash_cmd' | 'todo';

export interface ChatMessage {
  id: string;
  role: Role;
  text: string;
  isStreaming: boolean;
  isError: boolean;
  createdAt: string;
  /** Tool-activity rows (role === 'tool'): the raw tool the agent invoked (e.g.
   *  "Bash", "mcp__browser-control__browser_navigate") — used for icon lookup. */
  tool?: string;
  /** Correlation key: AgentActivity.call_id for CLI tool calls, or the
   *  client-driven actionId for browser-control round-trips. */
  actionId?: string;
  toolPhase?: 'start' | 'done';
  toolOk?: boolean;
  /** Pre-humanized display label (e.g. "Browser · Navigate"), done-suffix stripped. */
  toolLabel?: string;
  /** True for a user message queued mid-turn (steering / side question). */
  steering?: boolean;
  /**
   * Outbound delivery state (contract 1 acks): 'pending' until msg_ack,
   * 'delivered' on ack, 'failed' when no ack arrived → "not delivered — retry".
   */
  delivery?: 'pending' | 'delivered' | 'failed';
  /** Bridge warned this queued steering message may have been dropped (A8). */
  steeringDropWarning?: boolean;
  /** Permission decision delivery: 'sending' until perm_ack; 'failed' restores the card. */
  permDelivery?: 'sending' | 'failed';
  /** Page context (picked elements, attachments) sent with this user message. */
  context?: MessageContext;
  /** Permission rows (role === 'permission'): plan / ask_user / tool_blocked. */
  permKind?: 'plan' | 'permission_denied' | 'ask_user' | 'tool_blocked';
  permTitle?: string;
  permOptions?: { id: string; label: string }[];
  permQuestions?: AskUserQuestionItem[];
  permToolName?: string;
  permResolved?: boolean;
  /** Sub-agents spawned during this assistant turn (Task tool). */
  subAgents?: SubAgentRow[];
  /** MEDIC watchdog fields (role === 'medic'). */
  medicPhase?: 'running' | 'healthy' | 'issue';
  medicOk?: boolean;
  medicTarget?: string;
  medicDiagnostics?: Record<string, unknown>;
  /** Parallel /ask fields (role === 'ask'). */
  questionId?: string;
  askDone?: boolean;
  askOk?: boolean;
  /** Parallel side-query source: /ask vs /cursor-ctx vs english coach. */
  askKind?: 'ask' | 'cursor_ctx' | 'cursor_task' | 'english_coach';
  /** Status chip fields (role === 'status'). */
  statusKind?:
    | 'interrupted'
    | 'context_recovered'
    | 'idle_evicted'
    | 'reconnected'
    | 'session_command'
    | 'bound_tab'
    | 'compacting'
    | 'compact_done'
    | 'compact_failed';
  statusDetail?: string;
  /** Slash command card fields (role === 'slash_cmd'). */
  slashKind?: 'usage' | 'model' | 'memory' | 'new' | 'compact' | 'status' | 'add_dir';
  slashTitle?: string;
  slashData?: Record<string, unknown>;
  /**
   * Stable per-turn id (role === 'assistant', from AiChunk.turn_id). When set,
   * this bubble's id is `'turn-' + turnId` and `segments` (if present) is the
   * source of truth for `text` — see turnSegments.ts. Legacy chunks without a
   * turn_id never set this and keep appending straight to `text`.
   */
  turnId?: string;
  /** Ordered thinking/text segments for a turn-tagged bubble. */
  segments?: TurnSegment[];
  /** Per-turn cost/latency summary (from TurnResult), once the turn completes. */
  turnMeta?: TurnMeta;
  /** Live todo checklist (role === 'todo'), from the agent's TodoWrite calls. */
  todos?: TodoItem[];
}

export interface SubAgentRow {
  agentId: string;
  name: string;
  description: string;
  phase: 'start' | 'activity' | 'done';
  ok?: boolean;
  activity?: string;
}

export interface SessionState {
  name: string;
  agent: Agent;
  cwd: string;
  /** chat | worker | manager | orchestrator — from bridge metadata */
  purpose?: string;
  /** Claude CLI model id for this session; unset = CLI default. */
  model?: string | null;
  /** Claude --agent slug for this session. */
  claude_agent?: string | null;
  lastUsed: string;
  messages: ChatMessage[];
  isConnected: boolean;
  /** True while we're loading history from chrome.storage */
  isLoadingHistory: boolean;
  /** Live observability (set while a turn runs). */
  activity?: string;
  turnStartedAt?: number;
  usageTotal?: { tokens: number; costUsd: number };
  /** Last turn's input_tokens — current context window occupancy (not cumulative). */
  contextTokens?: number;
  /** True while the MEDIC watchdog is running — routes ai_chunk to the MedicCard. */
  medicRunning?: boolean;
  /** Bridge subprocess has an in-flight turn (from GET /sessions). */
  turnRunning?: boolean;
  /** Session-bound browser tab (mirrors chrome.storage; updated on bind). */
  boundTab?: BoundTab | null;
  /** User must pick among multiple matching tabs. */
  tabPickPrompt?: {
    reason: string;
    hintUrl?: string;
    candidates: BrowserTabSummary[];
  };
  /** Token-efficiency coaching from bridge (model switch / auto-compact notice). */
  coachHint?: SessionCoachHint | null;
  /** POST /actions returned 503 — no extension WS for this session name. */
  browserExtensionDisconnected?: boolean;
  /**
   * Kind of pending interactive request ('plan' / 'ask_user' / 'tool_blocked'),
   * fed by permission frames AND the /sessions `awaiting` field (contract 2).
   * Explicit state — replaces string-matching on the activity label.
   */
  awaitingKind?: string | null;
  /** Liveness (contract 2) — undefined on bridges that predate the fields. */
  lastOutputAt?: number | null; // epoch MILLISECONDS (converted from bridge seconds)
  currentTool?: string | null;
  queuedTurns?: number;
  /** Bridge-side compaction in progress (driven by A7 frames). */
  compacting?: boolean;
  /** FIFO of un-flushed steering message ids (message id === client_msg_id). */
  steeringQueue?: string[];
  /** Token count at which the user dismissed the "session getting expensive" banner. */
  compactBannerDismissedAt?: number;
}

export interface SessionCoachHint {
  level: 'info' | 'warn' | 'action';
  title: string;
  body: string;
  suggestedModel?: string | null;
  autoAction?: 'none' | 'compact';
}

export interface StoreState {
  sessions: Record<string, SessionState>;
  activeSession: string | null;
  reconnecting: boolean;
  /** Bridge HTTP unreachable (poll/transcript failures) — distinct from WS `reconnecting`. */
  bridgeUnreachable: boolean;
  /** Active top-level panel view. */
  view: 'chat' | 'whatsapp' | 'email' | 'calendar' | 'meta_ads' | 'tasks';
}

export type StoreAction =
  | { type: 'SET_SESSIONS'; infos: Record<string, SessionInfo> }
  | { type: 'ADD_SESSION'; name: string; agent: Agent; cwd: string; purpose?: string }
  | { type: 'REMOVE_SESSION'; name: string }
  | { type: 'SET_ACTIVE'; name: string }
  | { type: 'SET_HISTORY'; name: string; messages: ChatMessage[]; force?: boolean }
  | { type: 'SESSION_STATUS'; name: string; connected: boolean }
  | { type: 'APPEND_USER'; session: string; id: string; text: string; context?: MessageContext }
  | { type: 'APPEND_QUEUED'; session: string; id: string; text: string; context?: MessageContext }
  | { type: 'SESSION_COMMAND'; session: string; id: string; text: string; hint: string }
  | { type: 'SET_BOUND_TAB'; session: string; tab: BoundTab | null }
  | { type: 'TAB_BOUND_ACK'; session: string; tab: BoundTab }
  | {
      type: 'SET_TAB_PICK';
      session: string;
      reason: string;
      hintUrl?: string;
      candidates: BrowserTabSummary[];
    }
  | { type: 'CLEAR_TAB_PICK'; session: string }
  | { type: 'CHUNK'; session: string; text: string; turnId?: string; blockIndex?: number }
  | { type: 'THINKING_CHUNK'; session: string; turnId?: string; text: string }
  | { type: 'TURN_RESULT'; session: string; turnId?: string; meta: TurnMeta }
  | { type: 'DONE'; session: string }
  | { type: 'ERROR'; session: string; text: string }
  | { type: 'ACTIVITY'; session: string; label: string }
  | { type: 'TOOL_CALL'; session: string; activity: AgentActivity }
  | { type: 'USAGE'; session: string; tokens: number; costUsd: number; inputTokens: number }
  | {
      type: 'SUBAGENT';
      session: string;
      agentId: string;
      name: string;
      description: string;
      phase: 'start' | 'activity' | 'done';
      ok?: boolean;
      activity?: string;
    }
  | {
      type: 'PERMISSION_REQUEST';
      session: string;
      requestId: string;
      kind: 'plan' | 'permission_denied' | 'ask_user' | 'tool_blocked';
      title: string;
      description: string;
      options: { id: string; label: string }[];
      questions?: AskUserQuestionItem[];
      toolName?: string;
    }
  | { type: 'PERMISSION_RESOLVE'; session: string; requestId: string }
  | { type: 'TURN_STATE'; session: string; running: boolean }
  | { type: 'TURN_INTERRUPTED'; session: string }
  /** Force-clear orphan Thinking/tools when bridge is idle but UI is stuck. */
  | { type: 'FORCE_TURN_IDLE'; session: string }
  | {
      type: 'TOOL_ACTIVITY';
      session: string;
      actionId: string;
      tool: string;
      phase: 'start' | 'done';
      ok?: boolean;
      summary?: string;
    }
  | { type: 'SET_RECONNECTING'; value: boolean }
  | {
      type: 'WATCHDOG_REPORT';
      session: string;
      phase: 'start' | 'chunk' | 'done' | 'error';
      text?: string;
      detail?: string;
      diagnostics?: Record<string, unknown>;
    }
  | { type: 'ASK_START'; session: string; questionId: string; question: string; askKind?: 'ask' | 'cursor_ctx' | 'cursor_task' | 'english_coach' }
  | { type: 'ASK_CHUNK'; session: string; questionId: string; text: string }
  | { type: 'ASK_DONE'; session: string; questionId: string; ok: boolean }
  | {
      type: 'CONTEXT_RECOVERY';
      session: string;
      recovered: boolean;
      detail?: string;
    }
  | { type: 'MEDIC_CHUNK'; session: string; text: string }
  | {
      type: 'LOAD_TRANSCRIPT';
      session: string;
      turns: { role: 'user' | 'assistant'; text: string }[];
      force?: boolean;
    }
  | {
      type: 'MERGE_TRANSCRIPT';
      session: string;
      turns: { role: 'user' | 'assistant'; text: string }[];
    }
  | {
      type: 'SLASH_CMD';
      session: string;
      kind: 'usage' | 'model' | 'memory' | 'new' | 'compact' | 'status' | 'add_dir';
      title: string;
      body: string;
      data: Record<string, unknown>;
    }
  | { type: 'TODO_UPDATE'; session: string; turnId?: string; todos: TodoItem[] }
  | { type: 'SESSION_COACH'; session: string; hint: SessionCoachHint }
  | { type: 'DISMISS_COACH'; session: string }
  | { type: 'SET_SESSION_MODEL'; session: string; model: string | null }
  | { type: 'SET_VIEW'; view: 'chat' | 'whatsapp' | 'email' | 'calendar' | 'meta_ads' | 'tasks' }
  | ReliabilityAction;

export const INITIAL_STATE: StoreState = {
  sessions: {},
  activeSession: null,
  reconnecting: false,
  bridgeUnreachable: false,
  view: 'chat',
};
