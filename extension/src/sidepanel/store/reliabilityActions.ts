/**
 * reliabilityActions.ts — reducer logic for the chat-reliability overhaul:
 * delivery acks + rollback (C3), steering queue management (C6),
 * compact visibility (C8), and bridge liveness mapping (C5 / contract 2).
 *
 * Kept out of sessionStore.ts so both files stay within the size budget.
 * Only type-imports from sessionStore — no runtime cycle.
 */
import type { SessionInfo } from '@/shared/frames';
import type { ChatMessage, SessionState, StoreState } from './sessionStore';
import { nextId, nowIso, updateSession } from './helpers';

/** Re-anchor local turnStartedAt to the bridge's turn_elapsed_s beyond this drift. */
const TURN_ELAPSED_RESYNC_MS = 5_000;

export type ReliabilityAction =
  | {
      type: 'MSG_DELIVERY';
      session: string;
      clientMsgId: string;
      delivery: 'pending' | 'delivered' | 'failed';
    }
  | {
      type: 'PERM_DELIVERY';
      session: string;
      requestId: string;
      state: 'sending' | 'failed' | null;
    }
  | { type: 'CANCEL_STEERING'; session: string; messageId: string }
  | { type: 'STEERING_DROP_WARNING'; session: string }
  | {
      type: 'COMPACT_STATE';
      session: string;
      phase: 'start' | 'done' | 'failed';
      detail?: string;
    }
  | { type: 'COMPACT_BANNER_DISMISS'; session: string; tokens: number }
  | { type: 'SET_BRIDGE_UNREACHABLE'; value: boolean };

const RELIABILITY_TYPES = new Set([
  'MSG_DELIVERY',
  'PERM_DELIVERY',
  'CANCEL_STEERING',
  'STEERING_DROP_WARNING',
  'COMPACT_STATE',
  'COMPACT_BANNER_DISMISS',
  'SET_BRIDGE_UNREACHABLE',
]);

export function isReliabilityAction(action: { type: string }): action is ReliabilityAction {
  return RELIABILITY_TYPES.has(action.type);
}

// ─── Liveness mapping (contract 2) ───────────────────────────────────────────

/**
 * Merge the new GET /sessions liveness fields into a SessionState.
 * A field the bridge did not send (undefined — old bridge) keeps the local
 * value; a field it DID send is authoritative, including explicit null.
 */
export function applyLivenessFields(session: SessionState, info: SessionInfo): SessionState {
  let next = session;
  if (info.last_output_at !== undefined) {
    next = {
      ...next,
      lastOutputAt: info.last_output_at == null ? null : info.last_output_at * 1000,
    };
  }
  if (info.current_tool !== undefined) next = { ...next, currentTool: info.current_tool };
  if (info.queued_turns !== undefined) next = { ...next, queuedTurns: info.queued_turns };
  if (info.awaiting !== undefined) next = { ...next, awaitingKind: info.awaiting };
  if (info.turn_running && info.turn_elapsed_s != null) {
    const derived = Date.now() - info.turn_elapsed_s * 1000;
    const drift = next.turnStartedAt ? Math.abs(next.turnStartedAt - derived) : Infinity;
    if (drift > TURN_ELAPSED_RESYNC_MS) next = { ...next, turnStartedAt: derived };
  }
  return next;
}

// ─── Steering queue (C6) ─────────────────────────────────────────────────────

/**
 * Flip the NEXT queued steering bubble to a normal user message when its turn
 * starts — matched by explicit client_msg_id (FIFO queue), never by scanning
 * for "the first steering-looking message" (which desyncs with 2+ queued).
 * Mutates `msgs` in place (caller owns the copy) and returns the popped queue.
 */
export function flushNextSteering(
  session: SessionState,
  msgs: ChatMessage[],
): string[] | undefined {
  const queue = session.steeringQueue ?? [];
  const flushId = queue[0];
  const idx = flushId
    ? msgs.findIndex((m) => m.id === flushId && m.steering)
    : msgs.findIndex((m) => m.role === 'user' && m.steering);
  if (idx >= 0) {
    msgs[idx] = { ...msgs[idx], steering: false, steeringDropWarning: undefined };
  }
  return flushId ? queue.slice(1) : session.steeringQueue;
}

// ─── Reducer ─────────────────────────────────────────────────────────────────

export function reduceReliability(state: StoreState, action: ReliabilityAction): StoreState {
  switch (action.type) {
    case 'MSG_DELIVERY':
      return updateSession(state, action.session, (s) =>
        applyMsgDelivery(s, action.clientMsgId, action.delivery),
      );

    case 'PERM_DELIVERY':
      return updateSession(state, action.session, (s) => ({
        ...s,
        messages: s.messages.map((m) =>
          m.role === 'permission' && m.actionId === action.requestId
            ? { ...m, permDelivery: action.state ?? undefined }
            : m,
        ),
      }));

    case 'CANCEL_STEERING':
      return updateSession(state, action.session, (s) => ({
        ...s,
        messages: s.messages.filter((m) => !(m.id === action.messageId && m.steering)),
        steeringQueue: s.steeringQueue?.filter((id) => id !== action.messageId),
      }));

    case 'STEERING_DROP_WARNING':
      return updateSession(state, action.session, (s) => {
        const targetId =
          s.steeringQueue?.[0] ?? s.messages.find((m) => m.role === 'user' && m.steering)?.id;
        if (!targetId) return s;
        return {
          ...s,
          messages: s.messages.map((m) =>
            m.id === targetId ? { ...m, steeringDropWarning: true } : m,
          ),
        };
      });

    case 'COMPACT_STATE':
      return updateSession(state, action.session, (s) => applyCompactState(s, action));

    case 'COMPACT_BANNER_DISMISS':
      return updateSession(state, action.session, (s) => ({
        ...s,
        compactBannerDismissedAt: action.tokens,
      }));

    case 'SET_BRIDGE_UNREACHABLE':
      return state.bridgeUnreachable === action.value
        ? state
        : { ...state, bridgeUnreachable: action.value };

    default:
      return state;
  }
}

function applyMsgDelivery(
  s: SessionState,
  clientMsgId: string,
  delivery: 'pending' | 'delivered' | 'failed',
): SessionState {
  const idx = s.messages.findIndex((m) => m.id === clientMsgId && m.role === 'user');
  if (idx < 0) return s;

  const msgs = [...s.messages];
  const target = msgs[idx];
  msgs[idx] = {
    ...target,
    delivery,
    steeringDropWarning: delivery === 'pending' ? undefined : target.steeringDropWarning,
  };

  let next: SessionState = { ...s, messages: msgs };

  // Rollback for a failed NON-steering send: drop the optimistic empty assistant
  // placeholder right after it and clear the "Thinking…" spinner — so the panel
  // shows "not delivered — retry" instead of spinning forever (C3).
  if (delivery === 'failed' && !target.steering) {
    const follower = msgs[idx + 1];
    if (follower?.role === 'assistant' && follower.isStreaming && !follower.text.trim()) {
      msgs.splice(idx + 1, 1);
    }
    if (!next.turnRunning) {
      next = {
        ...next,
        activity: next.activity === 'Thinking…' ? undefined : next.activity,
        turnStartedAt: undefined,
      };
    }
  }
  return next;
}

function applyCompactState(
  s: SessionState,
  action: { phase: 'start' | 'done' | 'failed'; detail?: string },
): SessionState {
  const msgs = [...s.messages];
  const runningIdx = msgs.findIndex((m) => m.statusKind === 'compacting' && m.isStreaming);

  if (action.phase === 'start') {
    if (runningIdx >= 0) return s; // already showing the card
    msgs.push({
      id: nextId(),
      role: 'status',
      text: '',
      isStreaming: true,
      isError: false,
      createdAt: nowIso(),
      statusKind: 'compacting',
      statusDetail: action.detail ?? 'Summarizing the conversation to free context…',
    });
    return { ...s, messages: msgs, compacting: true };
  }

  const doneKind = action.phase === 'done' ? ('compact_done' as const) : ('compact_failed' as const);
  const doneMsg: ChatMessage = {
    id: runningIdx >= 0 ? msgs[runningIdx].id : nextId(),
    role: 'status',
    text: '',
    isStreaming: false,
    isError: false,
    createdAt: runningIdx >= 0 ? msgs[runningIdx].createdAt : nowIso(),
    statusKind: doneKind,
    statusDetail: action.detail,
  };
  if (runningIdx >= 0) msgs[runningIdx] = doneMsg;
  else msgs.push(doneMsg);
  return { ...s, messages: msgs, compacting: false };
}
