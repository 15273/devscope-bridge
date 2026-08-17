/**
 * sessionAttention.ts — detect when a session needs user input (approval, questions, reply).
 */
import type { SessionState } from '../store/sessionStore';
import { findPendingPermission } from '../store/sessionStore';
import { deriveWorkingState } from './workingState';
import { quickRepliesFromMessages } from './parseNumberedChoices';
import { findRunningTool } from './transcriptSync';

export type AttentionReason = 'approval' | 'questions' | 'reply';

export interface SessionAttention {
  sessionName: string;
  reason: AttentionReason;
  /** Stable id to dedupe alert side-effects. */
  signature: string;
  label: string;
}

function lastFinishedAssistantIndex(messages: SessionState['messages']): number {
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i];
    if (m.role === 'assistant' && !m.isStreaming && m.text.trim()) return i;
  }
  return -1;
}

export function getSessionAttention(session: SessionState): SessionAttention | null {
  const pending = findPendingPermission(session.messages);
  const awaitingApproval = Boolean(pending);
  const ws = deriveWorkingState(session, awaitingApproval);

  if (ws.isWorking && !ws.awaitingApproval) return null;

  if (ws.awaitingApproval) {
    if (pending) {
      const hasQuestions = (pending.permQuestions?.length ?? 0) > 0;
      return {
        sessionName: session.name,
        reason: hasQuestions ? 'questions' : 'approval',
        signature: `perm:${pending.id}`,
        label: hasQuestions ? 'Waiting for your answers' : 'Waiting for your approval',
      };
    }
    const activity = session.activity?.trim() || 'Waiting for your approval';
    return {
      sessionName: session.name,
      reason: 'approval',
      signature: `activity:${activity}`,
      label: activity,
    };
  }

  const streaming = session.messages.some((m) => m.role === 'assistant' && m.isStreaming);
  if (session.turnRunning || streaming || findRunningTool(session.messages)) return null;

  const replies = quickRepliesFromMessages(session.messages);
  if (replies.length === 0) return null;

  const idx = lastFinishedAssistantIndex(session.messages);
  if (idx < 0) return null;
  const msg = session.messages[idx];

  return {
    sessionName: session.name,
    reason: 'reply',
    signature: `reply:${msg.id}`,
    label: 'Waiting for your reply',
  };
}

/** Strip highlight + pulse — only structured approval/questions (not quick-reply chips). */
export function needsUrgentStripAttention(att: SessionAttention | undefined): boolean {
  return att?.reason === 'approval' || att?.reason === 'questions';
}

export function buildAttentionMap(sessions: SessionState[]): Map<string, SessionAttention> {
  const map = new Map<string, SessionAttention>();
  for (const session of sessions) {
    const att = getSessionAttention(session);
    if (att) map.set(session.name, att);
  }
  return map;
}
