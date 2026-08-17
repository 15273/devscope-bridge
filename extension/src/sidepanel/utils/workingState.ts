/**
 * workingState.ts — single source of truth for "Working" UI across strip, chat,
 * footer, Stop button, and composer. Anchored on bridge turn_running when present.
 */
import type { ChatMessage, SessionState } from '../store/sessionStore';
import { findRunningTool } from './transcriptSync';

export interface WorkingState {
  /** Agent turn in progress (not waiting on user approval). */
  isWorking: boolean;
  /** Show Stop / interrupt affordance. */
  showStop: boolean;
  /** Primary status line for strip, footer, composer. */
  statusLabel: string;
  /** Mid-turn steering messages waiting in Claude's queue. */
  queuedSteeringCount: number;
  awaitingApproval: boolean;
}

/** Turn considered stuck when it runs this long with zero output (amber strip). */
export const STUCK_AFTER_NO_OUTPUT_MS = 90_000;

/**
 * Auto-compact threshold in billable tokens. Mirrors the bridge's
 * `orchestrator_config` default (400k) — the bridge does not expose the value
 * over HTTP yet, so keep this constant in sync manually.
 */
export const AUTO_COMPACT_THRESHOLD_TOKENS = 400_000;
/** Warn ("session getting expensive") at this fraction of the auto-compact threshold. */
export const COMPACT_WARN_RATIO = 0.8;
/** After the user dismisses the warning, re-show once usage grew by this much. */
const COMPACT_WARN_REDISMISS_TOKENS = 50_000;

/** User messages queued mid-turn (after the in-flight assistant bubble). */
export function countQueuedSteering(messages: ChatMessage[], turnActive = true): number {
  if (!turnActive) return 0;
  const streamIdx = messages.findIndex((m) => m.role === 'assistant' && m.isStreaming);
  let count = 0;
  const startFrom = streamIdx >= 0 ? streamIdx + 1 : 0;
  for (let i = messages.length - 1; i >= startFrom; i--) {
    const m = messages[i];
    if (m.role === 'user' && m.steering) count++;
    else if (m.role === 'user' || m.role === 'assistant') break;
  }
  return count;
}

/**
 * True when a running turn produced no output for STUCK_AFTER_NO_OUTPUT_MS.
 * Requires the bridge's `last_output_at` (contract 2) — old bridges give no
 * signal, so we never cry stuck without evidence.
 */
export function isTurnStuck(session: SessionState, now: number = Date.now()): boolean {
  if (session.turnRunning !== true) return false;
  if (session.awaitingKind) return false;
  if (session.lastOutputAt == null) return false;
  return now - session.lastOutputAt > STUCK_AFTER_NO_OUTPUT_MS;
}

/** Show the proactive "Session getting expensive — Compact now" banner? (C8) */
export function shouldWarnCompact(session: SessionState): boolean {
  if (session.compacting) return false;
  const tokens = session.usageTotal?.tokens ?? 0;
  if (tokens < AUTO_COMPACT_THRESHOLD_TOKENS * COMPACT_WARN_RATIO) return false;
  const dismissedAt = session.compactBannerDismissedAt;
  if (dismissedAt == null) return true;
  return tokens >= dismissedAt + COMPACT_WARN_REDISMISS_TOKENS;
}

export function deriveWorkingState(
  session: SessionState,
  awaitingApproval: boolean,
): WorkingState {
  const runningTool = findRunningTool(session.messages);
  const streaming = session.messages.some((m) => m.role === 'assistant' && m.isStreaming);
  const turnRunning = session.turnRunning === true;
  const turnActive = turnRunning || streaming || Boolean(runningTool);
  // Bridge queued_turns (contract 2) is authoritative when larger — local
  // steering bubbles can be lost to transcript rebuilds.
  const queued = Math.max(
    countQueuedSteering(session.messages, turnActive),
    turnRunning ? session.queuedTurns ?? 0 : 0,
  );
  const activity = session.activity?.trim() ?? '';
  // Explicit awaitingKind (permission frames + /sessions.awaiting) — no more
  // string-matching on the English activity label.
  const awaiting = awaitingApproval || Boolean(session.awaitingKind);

  const staleThinking =
    !turnRunning &&
    !streaming &&
    !runningTool &&
    !awaiting &&
    Boolean(session.turnStartedAt) &&
    (activity === 'Thinking…' || activity === 'Working…' || activity === '');

  const isWorking =
    !awaiting &&
    !staleThinking &&
    (turnRunning ||
      streaming ||
      Boolean(runningTool) ||
      (Boolean(session.turnStartedAt) && activity !== ''));

  const currentTool = session.currentTool ?? runningTool;

  let statusLabel = '';
  if (awaiting) {
    statusLabel = activity || 'Waiting for your approval';
  } else if (queued > 0 && turnActive) {
    statusLabel = queued === 1 ? '1 turn queued · /interrupt to skip' : `${queued} turns queued · /interrupt`;
  } else if (activity && activity !== 'Thinking…' && activity !== runningTool) {
    statusLabel = activity;
  } else if (currentTool && isWorking) {
    statusLabel = `${currentTool}…`;
  } else if (runningTool || isWorking) {
    statusLabel = 'Working…';
  }

  return {
    isWorking,
    showStop: isWorking && !awaiting,
    statusLabel,
    queuedSteeringCount: queued,
    awaitingApproval: awaiting,
  };
}
