/**
 * sessionStore.ts — central state for multi-session management.
 *
 * Uses a single useReducer. All WS-sourced actions are session-scoped.
 * Chat history is persisted to chrome.storage.local on every mutation (per-profile
 * cache). Initial load merges with the bridge transcript so all Chrome profiles
 * see the same conversation.
 */
import type { Agent, AgentActivity, AskUserQuestionItem, SessionInfo, MessageContext, TodoItem } from '@/shared/frames';
import type { BoundTab, BrowserTabSummary } from '@/shared/tabBinding';
import {
  backfillMessageText,
  buildMessagesFromTranscript,
  hasEmptyStreamingAssistant,
  mergeTranscriptIntoMessages,
} from '../utils/transcriptSync';
import { upsertToolCallRow } from './toolActivityReducer';
import { isBrowserExtensionDisconnectedError } from '../utils/browserDisconnect';
import { nextId, nowIso, updateSession } from './helpers';
import {
  applyLivenessFields,
  flushNextSteering,
  isReliabilityAction,
  reduceReliability,
  type ReliabilityAction,
} from './reliabilityActions';
import {
  appendTextDelta,
  appendThinkingDelta,
  markThinkingDone,
  segmentsText,
  type TurnMeta,
  type TurnSegment,
} from './turnSegments';

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

/** Last unresolved permission card that still needs a user decision. */
export function findPendingPermission(messages: ChatMessage[]): ChatMessage | undefined {
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i];
    if (m.role !== 'permission' || m.permResolved) continue;
    if (m.permKind === 'permission_denied') continue;
    if ((m.permOptions?.length ?? 0) > 0) return m;
    if ((m.permQuestions?.length ?? 0) > 0) return m;
  }
  return undefined;
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

function newAssistantMsg(text = ''): ChatMessage {
  return { id: nextId(), role: 'assistant', text, isStreaming: true, isError: false, createdAt: nowIso() };
}

/**
 * Index of the assistant bubble already tagged with `turnId`, or — failing
 * that — an already-open untagged streaming placeholder (the eager bubble
 * APPEND_USER opens before the first chunk arrives) that should adopt it.
 * Returns -1 when neither exists (a fresh bubble must be created).
 *
 * Relies on a cross-file invariant: at most one assistant bubble streams at
 * a time — the composer gates APPEND_USER while a turn is working,
 * APPEND_QUEUED never creates a placeholder of its own, and the bridge runs
 * one turn per session. So "the untagged streaming placeholder" is never
 * ambiguous between two candidates.
 */
function findTurnAssistantIdx(msgs: ChatMessage[], turnId: string): number {
  const tagged = msgs.findIndex((m) => m.role === 'assistant' && m.turnId === turnId);
  if (tagged >= 0) return tagged;
  return msgs.findIndex((m) => m.role === 'assistant' && m.isStreaming && !m.turnId);
}

/** Stamp a turnId + stable id onto a bubble that doesn't carry one yet. */
function attachTurnId(msg: ChatMessage, turnId: string): ChatMessage {
  return msg.turnId ? msg : { ...msg, id: `turn-${turnId}`, turnId };
}

function newTurnAssistantMsg(turnId: string): ChatMessage {
  return {
    id: `turn-${turnId}`,
    role: 'assistant',
    text: '',
    isStreaming: true,
    isError: false,
    createdAt: nowIso(),
    turnId,
  };
}

/** Index of the last still-streaming assistant message, or -1. */
function lastStreamingAssistantIdx(msgs: ChatMessage[]): number {
  for (let i = msgs.length - 1; i >= 0; i--) {
    if (msgs[i].role === 'assistant' && msgs[i].isStreaming) return i;
  }
  return -1;
}

/** Mark in-flight browser tool rows done when the turn ends without a tool_activity done. */
function finalizeOrphanRunningTools(msgs: ChatMessage[]): ChatMessage[] {
  let changed = false;
  const next = msgs.map((m) => {
    if (m.role !== 'tool' || m.toolPhase !== 'start') return m;
    changed = true;
    return {
      ...m,
      toolPhase: 'done' as const,
      toolOk: false,
      text: m.text || 'timed out or interrupted',
    };
  });
  return changed ? next : msgs;
}

/**
 * How long a freshly-opened, still-empty assistant placeholder is protected
 * from turn-idle cleanup. The session poll runs every 2.5s and reports the
 * bridge's view, which lags a just-sent message — so a poll can say
 * turn_running=false for a turn the bridge has simply not started yet.
 */
const EMPTY_PLACEHOLDER_GRACE_MS = 5_000;

/** Assistant bubble with nothing to show: no text, no segments, not an error. */
export function isEmptyAssistantBubble(message: ChatMessage): boolean {
  return (
    message.role === 'assistant' &&
    !message.text.trim() &&
    !message.segments?.length &&
    !message.isError
  );
}

/**
 * Bridge says idle — clear stale working UI (orphan tools, steering queue, spinners).
 *
 * `force` skips the empty-placeholder grace window: FORCE_TURN_IDLE is the
 * panel deliberately stopping everything, not a report that might be stale.
 */
function applyTurnIdleCleanup(session: SessionState, force = false): SessionState {
  let changed = false;
  const messages: ChatMessage[] = [];
  for (const m of session.messages) {
    if (m.role === 'assistant' && m.isStreaming && isEmptyAssistantBubble(m)) {
      // Nothing has arrived for this bubble yet. Finalizing it here would leave
      // an empty, non-streaming assistant message in the transcript forever —
      // and chunks that land afterwards open a NEW bubble, so the empty one
      // never fills in. Inside the grace window the idle report is assumed
      // stale and the placeholder keeps waiting; past it the turn really did
      // end with nothing, so drop the bubble rather than freeze it empty.
      if (!force && Date.now() - new Date(m.createdAt).getTime() < EMPTY_PLACEHOLDER_GRACE_MS) {
        messages.push(m);
        continue;
      }
      changed = true;
      continue;
    }
    if (m.role === 'assistant' && m.isStreaming) {
      changed = true;
      messages.push({ ...m, isStreaming: false });
      continue;
    }
    if (m.role === 'user' && m.steering) {
      changed = true;
      messages.push({ ...m, steering: false });
      continue;
    }
    messages.push(m);
  }
  const finalized = finalizeOrphanRunningTools(messages);
  if (
    !changed &&
    finalized === messages &&
    !session.turnStartedAt &&
    !session.activity?.trim()
  ) {
    return session;
  }
  return {
    ...session,
    messages: finalized,
    activity: undefined,
    turnStartedAt: undefined,
    currentTool: null,
    steeringQueue: undefined,
  };
}

function sessionHasStaleWorkingState(session: SessionState): boolean {
  return (
    session.turnRunning === true ||
    session.turnStartedAt != null ||
    Boolean(session.activity?.trim()) ||
    session.messages.some((m) => m.role === 'assistant' && m.isStreaming) ||
    session.messages.some((m) => m.role === 'tool' && m.toolPhase === 'start') ||
    session.messages.some((m) => m.role === 'user' && m.steering)
  );
}

/** Exported for the panel sweeper — bridge idle but UI still "Thinking…". */
export function sessionLooksStuckWorking(session: SessionState): boolean {
  return sessionHasStaleWorkingState(session) && session.turnRunning !== true;
}

/** Insert English coach / side-query cards after the user turn, before the assistant reply. */
function insertSideQueryCard(msgs: ChatMessage[], card: ChatMessage): ChatMessage[] {
  const next = [...msgs];
  let insertAt = next.length;
  const last = next[next.length - 1];
  if (last?.role === 'assistant' && last.isStreaming) {
    insertAt = next.length - 1;
  } else {
    for (let i = next.length - 1; i >= 0; i--) {
      if (next[i].role === 'user' && !next[i].steering) {
        insertAt = i + 1;
        break;
      }
    }
  }
  next.splice(insertAt, 0, card);
  return next;
}

export function storeReducer(state: StoreState, action: StoreAction): StoreState {
  if (isReliabilityAction(action)) {
    return reduceReliability(state, action);
  }
  switch (action.type) {
    case 'SET_SESSIONS': {
      const next: Record<string, SessionState> = {};
      for (const [name, info] of Object.entries(action.infos)) {
        const existing = state.sessions[name];
        let session: SessionState = existing
          ? {
              ...existing,
              lastUsed: info.last_used,
              agent: info.agent ?? existing.agent,
              cwd: info.cwd ?? existing.cwd,
              model: info.model ?? existing.model ?? null,
              purpose: info.purpose ?? existing.purpose,
              turnRunning: info.turn_running ?? false,
            }
          : {
              name,
              agent: info.agent ?? 'claude',
              cwd: info.cwd ?? '',
              purpose: info.purpose ?? 'chat',
              model: info.model ?? null,
              lastUsed: info.last_used,
              messages: [],
              isConnected: false,
              isLoadingHistory: true,
              turnRunning: info.turn_running ?? false,
            };
        // Bridge says the turn ended — clear stale working UI (missed turn_state WS frames).
        if (existing && info.turn_running === false && sessionHasStaleWorkingState(existing)) {
          session = applyTurnIdleCleanup(session);
        }
        // Bridge says a turn started while the UI lost track (e.g. PTY / missed frames).
        if (existing && info.turn_running === true && !existing.turnStartedAt) {
          session = {
            ...session,
            turnStartedAt: Date.now(),
            activity: session.activity ?? 'Working…',
          };
        }
        // Liveness fields (contract 2) — absent on old bridges, authoritative when sent.
        session = applyLivenessFields(session, info);
        next[name] = session;
      }
      const activeStillExists = state.activeSession && next[state.activeSession];
      const newActive = activeStillExists
        ? state.activeSession
        : Object.keys(next)[0] ?? null;
      return { ...state, sessions: next, activeSession: newActive };
    }

    case 'ADD_SESSION': {
      const session: SessionState = {
        name: action.name,
        agent: action.agent,
        cwd: action.cwd,
        purpose: action.purpose ?? 'chat',
        lastUsed: new Date().toISOString(),
        messages: [],
        isConnected: false,
        isLoadingHistory: false,
      };
      return {
        ...state,
        sessions: { ...state.sessions, [action.name]: session },
        activeSession: action.name,
      };
    }

    case 'REMOVE_SESSION': {
      const { [action.name]: _removed, ...rest } = state.sessions;
      const names = Object.keys(rest);
      const newActive =
        state.activeSession === action.name ? (names[0] ?? null) : state.activeSession;
      return { ...state, sessions: rest, activeSession: newActive };
    }

    case 'SET_ACTIVE':
      return { ...state, activeSession: action.name };

    case 'SET_HISTORY':
      return updateSession(state, action.name, (s) => {
        // Ignore stale history loads after the user already sent a message.
        if (!action.force && !s.isLoadingHistory) return s;
        return {
          ...s,
          messages: action.messages,
          isLoadingHistory: false,
        };
      });

    case 'SESSION_STATUS':
      return updateSession(state, action.name, (s) => ({
        ...s,
        isConnected: action.connected,
        ...(action.connected ? { browserExtensionDisconnected: false } : {}),
      }));

    case 'APPEND_USER':
      return updateSession(state, action.session, (s) => ({
        ...s,
        isLoadingHistory: false,
        activity: 'Thinking…',
        turnStartedAt: Date.now(),
        messages: [
          ...s.messages,
          {
            id: action.id,
            role: 'user',
            text: action.text,
            context: action.context,
            isStreaming: false,
            isError: false,
            createdAt: nowIso(),
            delivery: 'pending',
          },
          newAssistantMsg(),
        ],
      }));

    case 'APPEND_QUEUED':
      // A steering message sent mid-turn: claude queues it and runs it as its
      // OWN turn after the current one. Add just the user bubble (no assistant
      // placeholder — the queued turn's first chunk opens its own bubble).
      return updateSession(state, action.session, (s) => ({
        ...s,
        isLoadingHistory: false,
        messages: [
          ...s.messages,
          {
            id: action.id,
            role: 'user',
            text: action.text,
            context: action.context,
            isStreaming: false,
            isError: false,
            createdAt: nowIso(),
            steering: true,
            delivery: 'pending',
          },
        ],
        steeringQueue: [...(s.steeringQueue ?? []), action.id],
      }));

    case 'SESSION_COMMAND':
      return updateSession(state, action.session, (s) => ({
        ...s,
        isLoadingHistory: false,
        messages: [
          ...s.messages,
          {
            id: action.id,
            role: 'status',
            text: '',
            isStreaming: false,
            isError: false,
            createdAt: nowIso(),
            statusKind: 'session_command',
            statusDetail: `${action.text} — ${action.hint}`,
          },
        ],
      }));

    case 'SET_BOUND_TAB':
      return updateSession(state, action.session, (s) => ({
        ...s,
        boundTab: action.tab,
        tabPickPrompt: undefined,
      }));

    case 'TAB_BOUND_ACK':
      return updateSession(state, action.session, (s) => ({
        ...s,
        boundTab: action.tab,
        tabPickPrompt: undefined,
        messages: [
          ...s.messages,
          {
            id: nextId(),
            role: 'status',
            text: '',
            isStreaming: false,
            isError: false,
            createdAt: nowIso(),
            statusKind: 'bound_tab',
            statusDetail: action.tab.title || action.tab.url,
          },
        ],
      }));

    case 'SET_TAB_PICK':
      return updateSession(state, action.session, (s) => ({
        ...s,
        tabPickPrompt: {
          reason: action.reason,
          hintUrl: action.hintUrl,
          candidates: action.candidates,
        },
      }));

    case 'CLEAR_TAB_PICK':
      return updateSession(state, action.session, (s) => ({
        ...s,
        tabPickPrompt: undefined,
      }));

    case 'PERMISSION_REQUEST': {
      const needsDecision =
        (action.kind === 'plan' || action.kind === 'ask_user' || action.kind === 'tool_blocked')
        && action.options.length > 0;
      return updateSession(state, action.session, (s) => {
        // Dedupe: pending-recovery fetches (C4) may replay a request the panel
        // already rendered from the live WS frame.
        if (s.messages.some((m) => m.role === 'permission' && m.actionId === action.requestId)) {
          return s;
        }
        const msgs = [...s.messages];
        const streamIdx = lastStreamingAssistantIdx(msgs);
        if (streamIdx >= 0) {
          msgs[streamIdx] = { ...msgs[streamIdx], isStreaming: false };
        }
        return {
          ...s,
          messages: [
            ...msgs,
            {
              id: nextId(),
              role: 'permission',
              text: action.description,
              isStreaming: false,
              isError: false,
              createdAt: nowIso(),
              actionId: action.requestId,
              permKind: action.kind,
              permTitle: action.title,
              permOptions: action.options,
              permQuestions: action.questions,
              permToolName: action.toolName,
              permResolved: action.kind === 'permission_denied',
            },
          ],
          activity: needsDecision
            ? (action.kind === 'ask_user' ? 'Waiting for your answers' : 'Waiting for your approval')
            : s.activity,
          turnStartedAt: needsDecision ? undefined : s.turnStartedAt,
          awaitingKind: needsDecision ? action.kind : s.awaitingKind,
        };
      });
    }

    case 'TURN_STATE':
      return updateSession(state, action.session, (s) => {
        const turnEnded = !action.running;
        if (!turnEnded) {
          return {
            ...s,
            turnRunning: true,
            turnStartedAt: s.turnStartedAt ?? Date.now(),
            activity: s.activity ?? 'Working…',
          };
        }
        return {
          ...applyTurnIdleCleanup(s),
          turnRunning: false,
        };
      });

    case 'TURN_INTERRUPTED':
      return updateSession(state, action.session, (s) => {
        const statusMsg: ChatMessage = {
          id: nextId(),
          role: 'status',
          text: '',
          isStreaming: false,
          isError: false,
          createdAt: nowIso(),
          statusKind: 'interrupted',
          statusDetail: 'היסטוריית הצ׳אט נשמרה — אפשר להמשיך לשלוח הודעות.',
        };
        const msgs = finalizeOrphanRunningTools(
          s.messages.map((m) =>
            m.role === 'assistant' && m.isStreaming ? { ...m, isStreaming: false } : m,
          ),
        );
        return {
          ...s,
          messages: [...msgs, statusMsg],
          turnRunning: false,
          turnStartedAt: undefined,
          activity: undefined,
        };
      });

    case 'FORCE_TURN_IDLE':
      return updateSession(state, action.session, (s) => ({
        ...applyTurnIdleCleanup(s, true),
        turnRunning: false,
      }));

    case 'PERMISSION_RESOLVE':
      return updateSession(state, action.session, (s) => ({
        ...s,
        awaitingKind: null,
        activity:
          s.activity === 'Waiting for your approval' ||
          s.activity === 'Waiting for your answers'
            ? undefined
            : s.activity,
        messages: s.messages.map((m) =>
          m.role === 'permission' && m.actionId === action.requestId
            ? { ...m, permResolved: true, permDelivery: undefined }
            : m,
        ),
      }));

    case 'SUBAGENT':
      return updateSession(state, action.session, (s) => {
        const msgs = [...s.messages];
        let idx = lastStreamingAssistantIdx(msgs);
        if (idx < 0) {
          for (let i = msgs.length - 1; i >= 0; i--) {
            if (msgs[i].role === 'assistant') {
              idx = i;
              break;
            }
          }
        }
        if (idx < 0) return s;
        const rows = [...(msgs[idx].subAgents ?? [])];
        const at = rows.findIndex((r) => r.agentId === action.agentId);
        if (action.phase === 'start') {
          if (at < 0) {
            rows.push({
              agentId: action.agentId,
              name: action.name,
              description: action.description,
              phase: 'start',
            });
          }
        } else if (at >= 0) {
          rows[at] = {
            ...rows[at],
            phase: action.phase,
            ok: action.phase === 'done' ? action.ok : rows[at].ok,
            activity: action.activity ?? rows[at].activity,
          };
        }
        msgs[idx] = { ...msgs[idx], subAgents: rows };
        return { ...s, messages: msgs };
      });

    case 'ACTIVITY':
      return updateSession(state, action.session, (s) => ({ ...s, activity: action.label }));

    case 'TOOL_CALL':
      // A tool call lifecycle event (running → done/error), correlated by call_id.
      // The first (running) event inserts one permanent transcript row; the later
      // done/error event for the SAME call_id updates that row in place — never a
      // second disconnected message.
      return updateSession(state, action.session, (s) => {
        const messages = upsertToolCallRow(s.messages, action.activity, { nextId, nowIso });
        const detail = action.activity.detail ?? '';
        const disconnect =
          action.activity.status === 'error' && isBrowserExtensionDisconnectedError(detail);
        return {
          ...s,
          messages,
          ...(disconnect ? { browserExtensionDisconnected: true } : {}),
        };
      });

    case 'USAGE':
      return updateSession(state, action.session, (s) => ({
        ...s,
        contextTokens: action.inputTokens,
        usageTotal: {
          tokens: (s.usageTotal?.tokens ?? 0) + action.tokens,
          costUsd: (s.usageTotal?.costUsd ?? 0) + action.costUsd,
        },
      }));

    case 'CHUNK':
      return updateSession(state, action.session, (s) => {
        const msgs = [...s.messages];
        if (action.turnId) {
          const turnId = action.turnId;
          const blockIndex = action.blockIndex ?? 0;
          const idx = findTurnAssistantIdx(msgs, turnId);
          if (idx >= 0) {
            const base = attachTurnId(msgs[idx], turnId);
            const segments = appendTextDelta(base.segments ?? [], blockIndex, action.text, Date.now());
            msgs[idx] = { ...base, segments, text: segmentsText(segments) };
            return { ...s, messages: msgs };
          }
          const steeringQueue = flushNextSteering(s, msgs);
          const segments = appendTextDelta([], blockIndex, action.text, Date.now());
          msgs.push({ ...newTurnAssistantMsg(turnId), segments, text: segmentsText(segments) });
          return { ...s, messages: msgs, steeringQueue };
        }
        // Legacy path (no turn_id) — behaves exactly as before Task 5.
        const idx = lastStreamingAssistantIdx(msgs);
        if (idx >= 0) {
          msgs[idx] = { ...msgs[idx], text: msgs[idx].text + action.text };
          return { ...s, messages: msgs };
        }
        // A queued (steering) turn started — flush by client_msg_id (FIFO),
        // then open a fresh assistant bubble.
        const steeringQueue = flushNextSteering(s, msgs);
        msgs.push(newAssistantMsg(action.text));
        return { ...s, messages: msgs, steeringQueue };
      });

    case 'THINKING_CHUNK':
      return updateSession(state, action.session, (s) => {
        const msgs = [...s.messages];
        const idx = action.turnId
          ? findTurnAssistantIdx(msgs, action.turnId)
          : lastStreamingAssistantIdx(msgs);
        if (idx >= 0) {
          const base = action.turnId ? attachTurnId(msgs[idx], action.turnId) : msgs[idx];
          const segments = appendThinkingDelta(base.segments ?? [], action.text, Date.now());
          msgs[idx] = { ...base, segments };
          return { ...s, messages: msgs };
        }
        if (!action.turnId) return s; // No bubble to attach to and no id to create one — drop.
        const steeringQueue = flushNextSteering(s, msgs);
        const segments = appendThinkingDelta([], action.text, Date.now());
        msgs.push({ ...newTurnAssistantMsg(action.turnId), segments });
        return { ...s, messages: msgs, steeringQueue };
      });

    case 'TURN_RESULT':
      return updateSession(state, action.session, (s) => {
        const msgs = [...s.messages];
        let idx = action.turnId
          ? msgs.findIndex((m) => m.role === 'assistant' && m.turnId === action.turnId)
          : -1;
        if (idx < 0) idx = lastStreamingAssistantIdx(msgs);
        if (idx < 0) return s; // Unknown turn and nothing streaming — drop silently.
        msgs[idx] = { ...msgs[idx], turnMeta: action.meta };
        return { ...s, messages: msgs };
      });

    case 'DONE':
      return updateSession(state, action.session, (s) => {
        let msgs = [...s.messages];
        const idx = lastStreamingAssistantIdx(msgs);
        if (idx >= 0) {
          const segments = msgs[idx].segments;
          msgs[idx] = {
            ...msgs[idx],
            isStreaming: false,
            ...(segments ? { segments: markThinkingDone(segments, Date.now()) } : {}),
          };
        }
        msgs = finalizeOrphanRunningTools(msgs);
        // Do not clear turnRunning here — ai_done is per assistant segment; TURN_STATE
        // from the bridge is the source of truth for whether the turn is still active.
        // BUT when the bridge never reported a running turn, there is nothing left
        // to wait for — clear the spinner state so "Thinking…" cannot persist.
        if (s.turnRunning) return { ...s, messages: msgs };
        return { ...s, messages: msgs, activity: undefined, turnStartedAt: undefined };
      });

    case 'ERROR':
      return updateSession(state, action.session, (s) => {
        let msgs = [...s.messages];
        const idx = lastStreamingAssistantIdx(msgs);
        if (idx >= 0) {
          msgs[idx] = { ...msgs[idx], text: action.text, isStreaming: false, isError: true };
        } else {
          msgs.push({ id: nextId(), role: 'assistant', text: action.text, isStreaming: false, isError: true, createdAt: nowIso() });
        }
        msgs = finalizeOrphanRunningTools(msgs);
        return { ...s, messages: msgs, activity: undefined, turnStartedAt: undefined, turnRunning: false };
      });

    case 'TOOL_ACTIVITY':
      return updateSession(state, action.session, (s) => {
        const msgs = [...s.messages];
        if (action.phase === 'done') {
          const idx = msgs.findIndex((m) => m.role === 'tool' && m.actionId === action.actionId);
          const summary = action.summary ?? (idx >= 0 ? msgs[idx].text : '');
          const failed = action.ok === false;
          const disconnect = failed && isBrowserExtensionDisconnectedError(summary);
          if (idx >= 0) {
            msgs[idx] = {
              ...msgs[idx],
              toolPhase: 'done',
              toolOk: action.ok,
              isError: failed,
              text: action.summary ?? msgs[idx].text,
            };
          }
          return {
            ...s,
            messages: msgs,
            ...(disconnect ? { browserExtensionDisconnected: true } : {}),
          };
        }
        const toolMsg: ChatMessage = {
          id: nextId(),
          role: 'tool',
          text: action.summary ?? '',
          isStreaming: false,
          isError: false,
          createdAt: nowIso(),
          tool: action.tool,
          actionId: action.actionId,
          toolPhase: 'start',
        };
        // Insert before a trailing streaming assistant message so CHUNK still
        // appends to that assistant message.
        const last = msgs[msgs.length - 1];
        if (last?.role === 'assistant' && last.isStreaming) {
          msgs.splice(msgs.length - 1, 0, toolMsg);
        } else {
          msgs.push(toolMsg);
        }
        return { ...s, messages: msgs };
      });

    case 'SET_RECONNECTING':
      return { ...state, reconnecting: action.value };

    case 'WATCHDOG_REPORT': {
      return updateSession(state, action.session, (s) => {
        const msgs = [...s.messages];
        if (action.phase === 'start') {
          // Open a new MedicCard bubble
          const medicMsg: ChatMessage = {
            id: nextId(),
            role: 'medic',
            text: action.text ?? '',
            isStreaming: true,
            isError: false,
            createdAt: nowIso(),
            medicPhase: 'running',
            medicTarget: action.session,
            medicDiagnostics: action.diagnostics,
          };
          msgs.push(medicMsg);
          return { ...s, messages: msgs, medicRunning: true };
        }
        if (action.phase === 'chunk') {
          // Append text to the last medic bubble
          const idx = [...msgs].reverse().findIndex((m) => m.role === 'medic' && m.isStreaming);
          const realIdx = idx >= 0 ? msgs.length - 1 - idx : -1;
          if (realIdx >= 0) {
            msgs[realIdx] = { ...msgs[realIdx], text: msgs[realIdx].text + (action.text ?? '') };
          }
          return { ...s, messages: msgs };
        }
        // phase === 'done' | 'error'
        const idx = [...msgs].reverse().findIndex((m) => m.role === 'medic' && m.isStreaming);
        const realIdx = idx >= 0 ? msgs.length - 1 - idx : -1;
        if (realIdx >= 0) {
          msgs[realIdx] = {
            ...msgs[realIdx],
            isStreaming: false,
            medicPhase: action.phase === 'done' ? 'healthy' : 'issue',
            medicOk: action.phase === 'done',
            text: msgs[realIdx].text + (action.text ?? ''),
          };
        }
        return { ...s, messages: msgs, medicRunning: false };
      });
    }

    case 'MEDIC_CHUNK': {
      // Route an ai_chunk that arrived while medicRunning=true to the MedicCard.
      return updateSession(state, action.session, (s) => {
        const msgs = [...s.messages];
        const idx = [...msgs].reverse().findIndex((m) => m.role === 'medic' && m.isStreaming);
        const realIdx = idx >= 0 ? msgs.length - 1 - idx : -1;
        if (realIdx >= 0) {
          msgs[realIdx] = { ...msgs[realIdx], text: msgs[realIdx].text + action.text };
        }
        return { ...s, messages: msgs };
      });
    }

    case 'ASK_START': {
      return updateSession(state, action.session, (s) => {
        const askMsg: ChatMessage = {
          id: nextId(),
          role: 'ask',
          text: '',
          isStreaming: true,
          isError: false,
          createdAt: nowIso(),
          questionId: action.questionId,
          askDone: false,
          askOk: undefined,
          askKind: action.askKind ?? 'ask',
          permTitle: action.question,
        };
        return { ...s, messages: insertSideQueryCard(s.messages, askMsg) };
      });
    }

    case 'ASK_CHUNK': {
      return updateSession(state, action.session, (s) => {
        const msgs = [...s.messages];
        const idx = msgs.findIndex((m) => m.role === 'ask' && m.questionId === action.questionId);
        if (idx >= 0) {
          msgs[idx] = { ...msgs[idx], text: msgs[idx].text + action.text };
        }
        return { ...s, messages: msgs };
      });
    }

    case 'ASK_DONE': {
      return updateSession(state, action.session, (s) => {
        const msgs = [...s.messages];
        const idx = msgs.findIndex((m) => m.role === 'ask' && m.questionId === action.questionId);
        if (idx >= 0) {
          msgs[idx] = { ...msgs[idx], isStreaming: false, askDone: true, askOk: action.ok };
        }
        return { ...s, messages: msgs };
      });
    }

    case 'CONTEXT_RECOVERY': {
      return updateSession(state, action.session, (s) => {
        if (!action.recovered) return s;
        const statusMsg: ChatMessage = {
          id: nextId(),
          role: 'status',
          text: '',
          isStreaming: false,
          isError: false,
          createdAt: nowIso(),
          statusKind: 'context_recovered',
          statusDetail: action.detail,
        };
        return { ...s, messages: [...s.messages, statusMsg] };
      });
    }

    case 'SLASH_CMD':
      return updateSession(state, action.session, (s) => {
        const card: ChatMessage = {
          id: nextId(),
          role: 'slash_cmd',
          text: action.body,
          isStreaming: false,
          isError: false,
          createdAt: nowIso(),
          slashKind: action.kind,
          slashTitle: action.title,
          slashData: action.data,
        };
        const modelFromCard =
          action.kind === 'model' && action.data && 'model' in action.data
            ? (action.data.model as string | null)
            : undefined;
        const resetUsage = action.kind === 'new' || action.kind === 'compact';
        return {
          ...s,
          model: modelFromCard !== undefined ? modelFromCard : s.model,
          messages: [...s.messages, card],
          ...(resetUsage ? { usageTotal: undefined, contextTokens: undefined, coachHint: null } : {}),
        };
      });

    case 'TODO_UPDATE':
      // One live checklist card per session — replaced in place (stable id)
      // rather than appended, so it always tracks the agent's latest plan.
      return updateSession(state, action.session, (s) => {
        const id = `todos-${action.session}`;
        const idx = s.messages.findIndex((m) => m.id === id);
        const card: ChatMessage = {
          id,
          role: 'todo',
          text: '',
          isStreaming: false,
          isError: false,
          createdAt: idx >= 0 ? s.messages[idx].createdAt : nowIso(),
          turnId: action.turnId,
          todos: action.todos,
        };
        if (idx < 0) return { ...s, messages: [...s.messages, card] };
        const messages = [...s.messages];
        messages[idx] = card;
        return { ...s, messages };
      });

    case 'SESSION_COACH':
      return updateSession(state, action.session, (s) => ({
        ...s,
        coachHint: action.hint,
      }));

    case 'DISMISS_COACH':
      return updateSession(state, action.session, (s) => ({
        ...s,
        coachHint: null,
      }));

    case 'SET_SESSION_MODEL':
      return updateSession(state, action.session, (s) => ({
        ...s,
        model: action.model,
      }));

    case 'LOAD_TRANSCRIPT': {
      return updateSession(state, action.session, (s) => {
        // Guard: never clobber a GENUINELY live streaming turn — unless forced
        // (e.g. after a terminal closes) OR the spinner is empty (WS chunks missed;
        // JSONL already has the reply and must be allowed to backfill).
        const isLiveStream = s.messages.some((m) => m.role === 'assistant' && m.isStreaming);
        if (isLiveStream && !action.force && !hasEmptyStreamingAssistant(s)) return s;

        // Rebuild user/assistant from transcript; keep ephemeral cards (coach, tools, …).
        //
        // A rebuilt bubble normally gets a fresh `tx-${i}` id — but a turn-tagged
        // assistant message ('turn-' + turnId, see ChatMessage.turnId) carries
        // `segments`/`turnMeta` that only live on the ORIGINAL message object, not
        // in the plain-text transcript. Blowing that away on every reload would
        // drop thinking blocks and the cost/latency footer.
        //
        // Match is TEXT-first, never positional: a purely positional cursor over
        // the tagged-only subset misattributes identity the moment tagged and
        // untagged assistant messages are interleaved (e.g. an old untagged
        // tx-* turn followed by a newer turn-tagged one) — the old turn would
        // consume the newer turn's tagged slot and inherit its turnId/turnMeta/
        // segments, while the newer turn falls through to a bare tx-i and loses
        // its own. Each tagged message is matched against a transcript assistant
        // turn by (trimmed) text equality and consumed at most once; a turn with
        // no text match falls back to a plain tx-i — dropping metadata for that
        // turn is acceptable, misattributing another turn's metadata is not.
        const turnTaggedAssistants = s.messages.filter(
          (m) => m.role === 'assistant' && m.id.startsWith('turn-'),
        );
        const consumedTaggedIds = new Set<string>();
        const messages = buildMessagesFromTranscript(
          s.messages,
          action.turns,
          (turn, i) => {
            if (turn.role === 'assistant') {
              const normalizedTurnText = turn.text.trim();
              const match = turnTaggedAssistants.find(
                (m) => !consumedTaggedIds.has(m.id) && m.text.trim() === normalizedTurnText,
              );
              if (match) {
                consumedTaggedIds.add(match.id);
                return match.text === turn.text
                  ? match
                  : { ...match, ...backfillMessageText(match, turn.text) };
              }
            }
            return {
              id: `tx-${i}`,
              role: turn.role,
              text: turn.text,
              isStreaming: false,
              isError: false,
              createdAt: nowIso(),
            };
          },
        );

        const idle = !s.turnRunning;
        return {
          ...s,
          messages,
          isLoadingHistory: false,
          ...(idle ? { activity: undefined, turnStartedAt: undefined } : {}),
        };
      });
    }

    case 'MERGE_TRANSCRIPT': {
      return updateSession(state, action.session, (s) => {
        let merged = mergeTranscriptIntoMessages(
          s.messages,
          action.turns,
          nextId,
          nowIso,
          // Keep spinner while bridge still runs tools after the first assistant segment.
          { keepStreaming: Boolean(s.turnRunning) },
        );
        if (!merged) return s;
        if (!s.turnRunning) {
          merged = finalizeOrphanRunningTools(merged);
        }
        const stillStreaming = merged.some((m) => m.role === 'assistant' && m.isStreaming);
        const stillTool = merged.some((m) => m.role === 'tool' && m.toolPhase === 'start');
        const idle = !s.turnRunning && !stillStreaming && !stillTool;
        return {
          ...s,
          messages: merged,
          isLoadingHistory: false,
          ...(idle ? { activity: undefined, turnStartedAt: undefined } : {}),
        };
      });
    }

    case 'SET_VIEW':
      return { ...state, view: action.view };

    default:
      return state;
  }
}
