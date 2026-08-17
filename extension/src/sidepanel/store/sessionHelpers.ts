/**
 * sessionHelpers.ts — message/session helpers shared by the store reducers.
 */
import { nextId, nowIso } from './helpers';
import type { ChatMessage, SessionState } from './sessionTypes';

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

export function newAssistantMsg(text = ''): ChatMessage {
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
export function findTurnAssistantIdx(msgs: ChatMessage[], turnId: string): number {
  const tagged = msgs.findIndex((m) => m.role === 'assistant' && m.turnId === turnId);
  if (tagged >= 0) return tagged;
  return msgs.findIndex((m) => m.role === 'assistant' && m.isStreaming && !m.turnId);
}

/** Stamp a turnId + stable id onto a bubble that doesn't carry one yet. */
export function attachTurnId(msg: ChatMessage, turnId: string): ChatMessage {
  return msg.turnId ? msg : { ...msg, id: `turn-${turnId}`, turnId };
}

export function newTurnAssistantMsg(turnId: string): ChatMessage {
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
export function lastStreamingAssistantIdx(msgs: ChatMessage[]): number {
  for (let i = msgs.length - 1; i >= 0; i--) {
    if (msgs[i].role === 'assistant' && msgs[i].isStreaming) return i;
  }
  return -1;
}

/** Mark in-flight browser tool rows done when the turn ends without a tool_activity done. */
export function finalizeOrphanRunningTools(msgs: ChatMessage[]): ChatMessage[] {
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
export function applyTurnIdleCleanup(session: SessionState, force = false): SessionState {
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

export function sessionHasStaleWorkingState(session: SessionState): boolean {
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
export function insertSideQueryCard(msgs: ChatMessage[], card: ChatMessage): ChatMessage[] {
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
