/**
 * turnSegments.ts — pure segment-based model for one assistant turn.
 *
 * A turn is a linear sequence of segments in emission order: extended-thinking
 * deltas accumulate into a single 'thinking' segment, text deltas accumulate
 * per Claude content-block index (a new block index — e.g. after a tool call
 * splits the reply — opens a new 'text' segment so the renderer can group
 * tool activity between them). All functions here are pure/immutable so the
 * reducer in sessionStore.ts stays a thin dispatcher.
 */

export interface ThinkingSegment {
  kind: 'thinking';
  text: string;
  startedAt: number;
  doneAt?: number;
}

export interface TextSegment {
  kind: 'text';
  blockIndex: number;
  text: string;
}

export interface TurnMeta {
  durationMs: number;
  costUsd: number;
  inputTokens: number;
  outputTokens: number;
  model?: string | null;
}

export type TurnSegment = ThinkingSegment | TextSegment;

/**
 * Append delta text to the right text segment, creating one as needed. Pure.
 *
 * Opening a NEW text segment closes any still-open trailing thinking segment
 * first: the bridge has no discrete "thinking done" event mid-turn (only at
 * DONE), but text starting to flow means the model has moved past that
 * thinking run. Without this, a `think -> tool call -> think again` turn
 * leaves the first thinking segment's `doneAt` unset forever, so it renders
 * as a permanently-stuck "חושב…" once the turn finishes.
 */
export function appendTextDelta(
  segments: TurnSegment[],
  blockIndex: number,
  text: string,
  now: number = Date.now(),
): TurnSegment[] {
  const last = segments[segments.length - 1];
  if (last?.kind === 'text' && last.blockIndex === blockIndex) {
    return [...segments.slice(0, -1), { ...last, text: last.text + text }];
  }
  const withClosedThinking =
    last?.kind === 'thinking' && last.doneAt === undefined
      ? [...segments.slice(0, -1), { ...last, doneAt: now }]
      : segments;
  return [...withClosedThinking, { kind: 'text', blockIndex, text }];
}

/** Append a thinking delta, accumulating into the last open thinking segment. Pure. */
export function appendThinkingDelta(
  segments: TurnSegment[],
  text: string,
  now: number,
): TurnSegment[] {
  const last = segments[segments.length - 1];
  if (last?.kind === 'thinking' && last.doneAt === undefined) {
    return [...segments.slice(0, -1), { ...last, text: last.text + text }];
  }
  return [...segments, { kind: 'thinking', text, startedAt: now }];
}

/**
 * Mark every still-open thinking segment as done (not just the first) — a
 * turn can carry more than one thinking run (think -> tool call -> think
 * again), and this is the only closing call made at turn DONE. Pure.
 */
export function markThinkingDone(segments: TurnSegment[], now: number): TurnSegment[] {
  if (!segments.some((s) => s.kind === 'thinking' && s.doneAt === undefined)) return segments;
  return segments.map((s) => (s.kind === 'thinking' && s.doneAt === undefined ? { ...s, doneAt: now } : s));
}

/** Joined visible text of all text segments — what TTS, persistence and transcript-compare use. */
export function segmentsText(segments: TurnSegment[]): string {
  return segments
    .filter((s): s is TextSegment => s.kind === 'text')
    .map((s) => s.text)
    .join('\n\n');
}
