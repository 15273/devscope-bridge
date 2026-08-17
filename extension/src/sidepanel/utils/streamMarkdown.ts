/**
 * streamMarkdown — helpers for rendering markdown live while it is still streaming
 * in, instead of waiting for the turn to finish.
 *
 * A partial markdown doc is very likely to have dangling syntax mid-token
 * (an unclosed ``` fence, a `**bold` that hasn't been closed yet, a trailing
 * single backtick). Left as-is, react-markdown either renders it literally or
 * produces jarring flashes as the closing marker arrives a token later.
 * `stabilizeStreamingMarkdown` closes those off defensively so every partial
 * chunk still parses into a clean, sane document.
 */
import { useEffect, useRef, useState } from 'react';

const DEFAULT_THROTTLE_MS = 100;
const FENCE_RE = /^```/;

/** Close dangling markdown so a partial doc parses cleanly: unclosed ``` fence,
 * unclosed **bold** or `inline code` at end-of-text. Pure. */
export function stabilizeStreamingMarkdown(text: string): string {
  const fenceCount = countLeadingFences(text);
  const insideOpenFence = fenceCount % 2 === 1;

  if (insideOpenFence) {
    return text.endsWith('\n') ? `${text}\`\`\`` : `${text}\n\`\`\``;
  }

  return closeDanglingInlineMarkers(text);
}

/** Count lines that start with ``` — the same rule markdown fence parsing uses. */
function countLeadingFences(text: string): number {
  let count = 0;
  for (const line of text.split('\n')) {
    if (FENCE_RE.test(line)) count += 1;
  }
  return count;
}

/** Outside any fence, close a trailing unmatched ** or a trailing unmatched `.
 * Parity is computed with completed fence-pair content removed first, so a
 * backtick or `**kwargs` inside a *closed* code block never flips parity for
 * the prose that follows it. */
function closeDanglingInlineMarkers(text: string): string {
  const outsideFences = stripClosedFenceLines(text);

  const boldCount = (outsideFences.match(/\*\*/g) ?? []).length;
  if (boldCount % 2 === 1) {
    return `${text}**`;
  }

  const backtickCount = (outsideFences.match(/`/g) ?? []).length;
  if (backtickCount % 2 === 1) {
    return `${text}\``;
  }

  return text;
}

/** Drop every line inside a completed ``` ... ``` pair (including the fence
 * delimiter lines themselves), keeping only lines genuinely outside a code
 * block. Uses the exact same line-start rule as countLeadingFences, so the
 * two never disagree about where a fence starts or ends — a mid-line ```
 * inside fenced content (e.g. a code sample showing "Use ``` to open") does
 * not confuse this pass the way a substring-based regex would. */
function stripClosedFenceLines(text: string): string {
  const kept: string[] = [];
  let inFence = false;

  for (const line of text.split('\n')) {
    if (FENCE_RE.test(line)) {
      inFence = !inFence;
      continue;
    }
    if (!inFence) kept.push(line);
  }

  return kept.join('\n');
}

/** Throttle hook: returns `text` re-sampled at most every `ms` (default 100),
 * always flushing the final value. */
export function useThrottledText(text: string, ms = DEFAULT_THROTTLE_MS): string {
  const [throttled, setThrottled] = useState(text);
  const lastFlushRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const now = Date.now();
    const elapsed = now - lastFlushRef.current;

    if (elapsed >= ms) {
      lastFlushRef.current = now;
      setThrottled(text);
      return;
    }

    const remaining = ms - elapsed;
    timerRef.current = setTimeout(() => {
      lastFlushRef.current = Date.now();
      setThrottled(text);
    }, remaining);

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [text, ms]);

  return throttled;
}
