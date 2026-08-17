/**
 * historyLoader — merge per-profile chrome.storage cache with the bridge transcript.
 *
 * Session metadata and JSONL transcripts live on the local dev-bridge (shared across
 * all Chrome profiles). Each profile only had its own chrome.storage.local copy of the
 * UI message list — so opening DevScope in another profile showed an empty or stale chat.
 */
import type { TranscriptTurn } from '../bridge';
import { fetchTranscript } from '../bridge';
import type { ChatMessage } from '../store/sessionStore';
import { buildMessagesFromTranscript } from './transcriptSync';
import { loadHistory } from './storage';

function transcriptMessage(turn: TranscriptTurn, index: number): ChatMessage {
  return {
    id: `tx-${index}`,
    role: turn.role,
    text: turn.text,
    isStreaming: false,
    isError: false,
    createdAt: new Date().toISOString(),
  };
}

/** Pure merge used in tests and initial load. */
export function mergeHistoryWithTranscript(
  local: ChatMessage[],
  turns: TranscriptTurn[],
): ChatMessage[] {
  if (turns.length === 0) return local;
  return buildMessagesFromTranscript(local, turns, transcriptMessage);
}

/** User/assistant rows only — for bridge transcript backfill (Cursor). */
export function messagesToBridgeTurns(messages: ChatMessage[]): TranscriptTurn[] {
  return messages
    .filter(
      (m) =>
        (m.role === 'user' || m.role === 'assistant') &&
        m.text.trim() &&
        !m.isStreaming &&
        !m.isError,
    )
    .map((m) => ({ role: m.role as 'user' | 'assistant', text: m.text.trim() }));
}

/**
 * Load chat history for a session: local cache + authoritative bridge transcript.
 * Ephemeral UI rows (tools, permissions, coach) from this profile's cache are kept.
 */
export async function loadSessionHistory(sessionName: string): Promise<ChatMessage[]> {
  const [local, turns] = await Promise.all([
    loadHistory(sessionName),
    fetchTranscript(sessionName).then((r) => r.turns, () => [] as TranscriptTurn[]),
  ]);
  return mergeHistoryWithTranscript(local, turns);
}
