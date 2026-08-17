/**
 * frameBatch.ts — pure, testable IPC coalescing buffer for offscreen.ts.
 *
 * The bridge streams `ai_chunk` / `thinking_chunk` frames one token-delta at a
 * time, which used to trigger one chrome.runtime.sendMessage per delta. This
 * batcher merges consecutive coalescible frames sharing the same
 * (type, session, turn_id, block_index) key within a short time window,
 * concatenating their `text`. Any other frame type flushes the buffer first,
 * so downstream consumers still see frames in the original stream order.
 */

const DEFAULT_WINDOW_MS = 40;

const COALESCIBLE_TYPES = new Set(['ai_chunk', 'thinking_chunk']);

interface CoalescibleFrame {
  type: string;
  session?: string;
  turn_id?: string | null;
  block_index?: number;
  text: string;
  [key: string]: unknown;
}

export interface FrameBatcher {
  push(frame: { type: string; session?: string }): void;
  /** Force-flush everything buffered (call on ws close). */
  flush(): void;
}

function isCoalescible(frame: { type: string }): frame is CoalescibleFrame {
  return COALESCIBLE_TYPES.has(frame.type);
}

function sameKey(a: CoalescibleFrame, b: CoalescibleFrame): boolean {
  return (
    a.type === b.type &&
    a.session === b.session &&
    a.turn_id === b.turn_id &&
    a.block_index === b.block_index
  );
}

export function createFrameBatcher(
  emit: (frame: unknown) => void,
  windowMs: number = DEFAULT_WINDOW_MS,
  schedule: (cb: () => void, ms: number) => void = (cb, ms) => {
    setTimeout(cb, ms);
  },
): FrameBatcher {
  let pending: CoalescibleFrame | null = null;
  /** Bumped on every flush so a timer armed for a stale pending buffer becomes a no-op. */
  let generation = 0;

  function flush(): void {
    generation += 1;
    if (pending) {
      emit(pending);
      pending = null;
    }
  }

  function push(frame: { type: string; session?: string }): void {
    if (!isCoalescible(frame)) {
      flush();
      emit(frame);
      return;
    }

    if (pending && sameKey(pending, frame)) {
      pending = { ...pending, text: pending.text + frame.text };
      return;
    }

    flush();
    pending = { ...frame };
    const scheduledGeneration = generation;
    schedule(() => {
      if (scheduledGeneration === generation) flush();
    }, windowMs);
  }

  return { push, flush };
}
