/**
 * StreamingIndicators — small status atoms shared by Chat.tsx's legacy
 * single-text path and SegmentedMessageBody's per-segment rendering. Pulled
 * out on its own so both can import it without Chat.tsx <-> SegmentedMessageBody
 * forming an import cycle.
 */
import { useEffect, useState } from 'react';
import { ListOrdered, Wrench } from 'lucide-react';
import { ClaudeSpark } from './ClaudeSpark';

/**
 * Rotating gerund set for the generic "Working…" placeholder. Deterministic
 * (bucketed by elapsed time), never Math.random — same turn re-renders (e.g.
 * on parent re-render) always show the same verb for the same elapsed bucket.
 */
const STATUS_VERBS = ['Thinking…', 'Reading…', 'Wiring…', 'Polishing…', 'Checking…'];
const STATUS_VERB_INTERVAL_MS = 4000;

/** Ticks once a second while `active`, returning ms elapsed since first active. */
function useElapsedMs(active: boolean): number {
  const [elapsedMs, setElapsedMs] = useState(0);

  useEffect(() => {
    if (!active) {
      setElapsedMs(0);
      return;
    }
    const startedAt = Date.now();
    const id = setInterval(() => setElapsedMs(Date.now() - startedAt), 1000);
    return () => clearInterval(id);
  }, [active]);

  return elapsedMs;
}

export function StreamingCursor() {
  return (
    <span className="ml-0.5 inline-block font-mono text-signal animate-cursor-pulse" aria-hidden>
      ▌
    </span>
  );
}

export function StreamingPlaceholder({
  statusLabel,
  runningTool,
  queuedSteeringCount = 0,
}: {
  statusLabel?: string;
  runningTool?: string;
  queuedSteeringCount?: number;
}) {
  // The generic fallback (no specific tool/queued label) rotates through a
  // small verb set every ~4s instead of sitting on a static "Working…".
  const isGenericFallback = !statusLabel && !runningTool;
  const elapsedMs = useElapsedMs(isGenericFallback);
  const rotatingVerb = STATUS_VERBS[Math.floor(elapsedMs / STATUS_VERB_INTERVAL_MS) % STATUS_VERBS.length];
  const label = statusLabel || (runningTool ? `${runningTool}…` : rotatingVerb);
  const isQueued = queuedSteeringCount > 0;
  const isToolish = !isQueued && Boolean(runningTool) && !statusLabel?.includes('queued');

  return (
    <div
      className={`flex items-center gap-2 rounded-sm px-1 py-1.5 ${
        isQueued
          ? 'border border-signal/30 bg-signal-subtle/50'
          : isToolish
            ? 'border border-signal/25 bg-signal-subtle/40'
            : ''
      }`}
    >
      {isQueued ? (
        <ListOrdered size={13} strokeWidth={2} className="flex-shrink-0 text-signal" />
      ) : isToolish ? (
        <Wrench size={13} strokeWidth={2} className="flex-shrink-0 text-signal" />
      ) : (
        <ClaudeSpark />
      )}
      <span className="min-w-0 truncate font-mono text-xs text-fg-muted">{label}</span>
      {!isQueued && <StreamingCursor />}
    </div>
  );
}
