/**
 * transcriptSync — heuristics for when the chat UI should reload from the
 * bridge's authoritative JSONL transcript (live WS chunks may be missed).
 */
import type { ChatMessage, SessionState } from '../store/sessionStore';
import { segmentsText, type TurnSegment } from '../store/turnSegments';

export type TranscriptTurn = { role: 'user' | 'assistant'; text: string };

/**
 * Rebuild a turn-tagged message's segments for a transcript text backfill.
 * SegmentedMessageBody renders `segments`, not `text`, for any turn-tagged
 * bubble — so a backfill that only overwrites `text` is invisible on screen.
 * Thinking segments carry no plain-text equivalent and are kept as-is; all
 * text segments collapse into a single one holding the transcript's text.
 */
export function rebuildSegmentsForBackfill(
  segments: TurnSegment[],
  txText: string,
): TurnSegment[] {
  const thinking = segments.filter((s) => s.kind === 'thinking');
  return [...thinking, { kind: 'text', blockIndex: 0, text: txText }];
}

/**
 * Fields to spread onto a message when backfilling its text from the
 * transcript. Keeps `segments` (if present) and `text` in sync — `text` is
 * always derived from the rebuilt segments so the two never disagree.
 *
 * Repairs only a REAL mismatch. SegmentedMessageBody keys its text blocks by
 * array position, so collapsing several text segments into one remounts every
 * block below it — a visible flash at the exact moment a turn completes, which
 * is when the transcript merge runs. When the segments already say what the
 * transcript says (modulo surrounding whitespace, which the JSONL writer and
 * the segment joiner disagree about routinely), there is nothing to repair:
 * hand back the SAME segments array so React keeps the DOM it already has.
 */
export function backfillMessageText(
  message: Pick<ChatMessage, 'segments'>,
  txText: string,
): { text: string; segments?: TurnSegment[] } {
  if (!message.segments) return { text: txText };
  const current = segmentsText(message.segments);
  if (current.trim() === txText.trim()) {
    return { text: current, segments: message.segments };
  }
  const segments = rebuildSegmentsForBackfill(message.segments, txText);
  return { text: segmentsText(segments), segments };
}

/** Roles not stored in the bridge JSONL transcript — must survive LOAD_TRANSCRIPT. */
const EPHEMERAL_ROLES = new Set<ChatMessage['role']>([
  'tool',
  'permission',
  'medic',
  'ask',
  'status',
  'slash_cmd',
  'todo',
]);

function countNonSteeringUsersBefore(messages: ChatMessage[], beforeIndex: number): number {
  let count = 0;
  for (let i = 0; i < beforeIndex; i++) {
    if (messages[i].role === 'user' && !messages[i].steering) count++;
  }
  return count;
}

/**
 * Rebuild user/assistant bubbles from transcript while preserving ephemeral UI rows
 * (English coach, tools, permissions, etc.) in their original positions.
 */
export function buildMessagesFromTranscript(
  existing: ChatMessage[],
  turns: TranscriptTurn[],
  makeMessage: (turn: TranscriptTurn, index: number) => ChatMessage,
): ChatMessage[] {
  // If the incoming transcript has fewer user turns than the UI already shows,
  // a compact reset the bridge transcript. Preserve existing panel messages so
  // the user doesn't lose conversation history.
  const existingUserCount = existing.filter((m) => m.role === 'user' && !m.steering).length;
  const newUserCount = turns.filter((t) => t.role === 'user').length;
  if (existingUserCount > 0 && newUserCount < existingUserCount) {
    return existing;
  }

  const fromTranscript = turns.map((turn, i) => makeMessage(turn, i));
  const ephemeral = existing.filter((m) => EPHEMERAL_ROLES.has(m.role));
  if (ephemeral.length === 0) return fromTranscript;

  const afterUserSlot = new Map<string, number>();
  for (const ep of ephemeral) {
    const idx = existing.findIndex((m) => m.id === ep.id);
    afterUserSlot.set(ep.id, countNonSteeringUsersBefore(existing, idx < 0 ? 0 : idx));
  }

  const result: ChatMessage[] = [];
  const inserted = new Set<string>();
  let usersSeen = 0;

  for (const txMsg of fromTranscript) {
    result.push(txMsg);
    if (txMsg.role === 'user') {
      usersSeen++;
      for (const ep of ephemeral) {
        if (afterUserSlot.get(ep.id) === usersSeen) {
          result.push(ep);
          inserted.add(ep.id);
        }
      }
    }
  }

  for (const ep of ephemeral) {
    if (!inserted.has(ep.id)) result.push(ep);
  }

  return result;
}

/** Index of the last message matching `pred`, or -1. */
function findLastIndex(messages: ChatMessage[], pred: (m: ChatMessage) => boolean): number {
  for (let i = messages.length - 1; i >= 0; i--) {
    if (pred(messages[i])) return i;
  }
  return -1;
}

function findLastAssistantIndex(messages: ChatMessage[]): number {
  return findLastIndex(messages, (m) => m.role === 'assistant');
}

/** Last in-flight browser/CLI tool row for the current turn (if any). */
export function findRunningTool(messages: ChatMessage[]): string | undefined {
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i];
    if (m.role === 'user' && !m.steering) break;
    if (m.role === 'tool' && m.toolPhase === 'start') return m.tool;
  }
  return undefined;
}

/** Empty (or whitespace-only) assistant bubble still marked as streaming. */
export function hasEmptyStreamingAssistant(session: SessionState): boolean {
  return session.messages.some(
    (m) => m.role === 'assistant' && m.isStreaming && !m.text.trim(),
  );
}

/**
 * True when the UI likely lags behind the on-disk transcript.
 * Call only when the bridge reports turn_running === false.
 */
export function needsTranscriptBackfill(session: SessionState): boolean {
  if (session.isLoadingHistory) return false;

  const msgs = session.messages;
  const lastAssistantIdx = findLastIndex(msgs, (m) => m.role === 'assistant');
  if (lastAssistantIdx < 0) return false;

  const lastAssistant = msgs[lastAssistantIdx];
  if (lastAssistant.isStreaming) return true;

  const lastUserIdx = findLastIndex(msgs, (m) => m.role === 'user' && !m.steering);
  if (lastUserIdx < 0 || lastAssistantIdx <= lastUserIdx) return false;

  if (!lastAssistant.text.trim()) return true;

  return false;
}

/** True while the bridge subprocess still has an in-flight turn. */
export function isSessionWorking(session: SessionState): boolean {
  if (session.turnRunning) return true;
  if (session.messages.some((m) => m.role === 'assistant' && m.isStreaming)) return true;
  if (findRunningTool(session.messages)) return true;
  const activity = session.activity?.trim();
  if (activity && !activity.startsWith('Waiting for')) return true;
  return false;
}

/**
 * True when the on-disk transcript has assistant content the UI has not shown yet.
 * Safe to call while turn_running — used for live tail-merge during active turns.
 */
export function transcriptAheadOfUi(session: SessionState, turns: TranscriptTurn[]): boolean {
  if (session.isLoadingHistory || turns.length === 0) return false;

  const txAssistants = turns.filter((t) => t.role === 'assistant');
  if (txAssistants.length === 0) return false;

  const uiAssistants = session.messages.filter((m) => m.role === 'assistant');
  const lastTx = txAssistants[txAssistants.length - 1];
  if (txAssistants.length > uiAssistants.length) return true;

  // UI already opened a placeholder for a turn not yet in the transcript.
  if (uiAssistants.length > txAssistants.length) return false;

  const lastMsg = session.messages[session.messages.length - 1];
  if (
    lastMsg?.role === 'assistant' &&
    lastMsg.isStreaming &&
    !lastMsg.text.trim()
  ) {
    return lastTx.text.trim().length > 0;
  }

  const lastUi = uiAssistants[uiAssistants.length - 1];
  if (!lastUi) return lastTx.text.trim().length > 0;
  if (lastUi.isStreaming && !lastUi.text.trim()) {
    return lastTx.text.trim().length > 0;
  }

  const txText = lastTx.text;
  const uiText = lastUi.text;
  if (!txText.trim()) return false;
  if (txText.length > uiText.length + 15) return true;
  if (txText.trim() !== uiText.trim() && txText.length > uiText.length) {
    return true;
  }
  return false;
}

export type MergeTranscriptOptions = {
  /** When true, keep isStreaming on the last assistant after text backfill (turn still active). */
  keepStreaming?: boolean;
};

/**
 * Merge transcript tail into UI messages without discarding ephemeral rows
 * (tools, permissions, medic, etc.). Returns null when nothing to update.
 */
export function mergeTranscriptIntoMessages(
  messages: ChatMessage[],
  turns: TranscriptTurn[],
  nextId: () => string,
  nowIso: () => string,
  opts: MergeTranscriptOptions = {},
): ChatMessage[] | null {
  if (turns.length === 0) return null;

  const keepStreaming = Boolean(opts.keepStreaming);
  const txAssistants = turns.filter((t) => t.role === 'assistant');
  if (txAssistants.length === 0) return null;

  const uiAssistants = messages.filter((m) => m.role === 'assistant');
  const lastTx = txAssistants[txAssistants.length - 1];
  const msgs = [...messages];
  let changed = false;

  const lastMsg = messages[messages.length - 1];
  if (
    lastMsg?.role === 'assistant' &&
    lastMsg.isStreaming &&
    uiAssistants.length > txAssistants.length
  ) {
    return null;
  }

  // UI opened a fresh assistant bubble for a turn that is not in the transcript yet.
  if (uiAssistants.length > txAssistants.length) return null;

  if (txAssistants.length > uiAssistants.length) {
    const extras = txAssistants.slice(uiAssistants.length);
    for (const turn of extras) {
      msgs.push({
        id: nextId(),
        role: 'assistant',
        text: turn.text,
        isStreaming: false,
        isError: false,
        createdAt: nowIso(),
      });
      changed = true;
    }
    return changed ? msgs : null;
  }

  const lastIdx = findLastAssistantIndex(msgs);
  if (lastIdx < 0) {
    msgs.push({
      id: nextId(),
      role: 'assistant',
      text: lastTx.text,
      isStreaming: false,
      isError: false,
      createdAt: nowIso(),
    });
    return msgs;
  }

  const lastUi = msgs[lastIdx];
  const txText = lastTx.text;
  if (lastUi.isStreaming) {
    // Never clobber a bubble that already has live content (CHUNK/segments are
    // the source of truth once streaming has started) — only backfill a still-
    // empty placeholder whose WS chunks may have been missed entirely.
    if (lastUi.text.trim() || !txText.trim() || uiAssistants.length > txAssistants.length) {
      return null;
    }
    msgs[lastIdx] = {
      ...lastUi,
      ...backfillMessageText(lastUi, txText),
      // Finalize when the turn is idle; keep the spinner if tools may still run.
      isStreaming: keepStreaming,
    };
    return msgs;
  }

  const uiText = lastUi.text;

  if (
    txText.length > uiText.length ||
    (txText.trim() && txText.trim() !== uiText.trim() && txText.length >= uiText.length)
  ) {
    msgs[lastIdx] = {
      ...lastUi,
      ...backfillMessageText(lastUi, txText),
      isStreaming: lastUi.isStreaming && txText.length <= uiText.length,
    };
    changed = true;
  }

  return changed ? msgs : null;
}
