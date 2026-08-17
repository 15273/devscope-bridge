/**
 * ThinkingBlock — collapsed dim strip for a turn's extended-thinking segment.
 *
 * Collapsed: Brain icon + "חושב…" (shimmering label while the model is still
 * thinking) or "חשב N שניות" once the segment is done. Click toggles an
 * expanded panel showing the raw thinking text — dim, small, scrollable.
 * Reduced-motion users get the global guard in tailwind.css (animation
 * durations collapse to ~0), so the shimmer never needs its own opt-out here.
 */
import { useState } from 'react';
import { Brain, ChevronRight } from 'lucide-react';
import { formatThinkingDuration } from '../utils/turnFormat';

interface ThinkingBlockProps {
  text: string;
  streaming: boolean;
  startedAt: number;
  doneAt?: number;
}

export function ThinkingBlock({ text, streaming, startedAt, doneAt }: ThinkingBlockProps) {
  const [expanded, setExpanded] = useState(false);

  const label = streaming || doneAt === undefined
    ? 'חושב…'
    : formatThinkingDuration(startedAt, doneAt);

  return (
    <div className="mb-1.5">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        className="flex items-center gap-1.5 rounded-sm px-1 py-1 text-xs text-fg-subtle transition-colors duration-fast ease-tool hover:text-fg-muted"
      >
        <Brain size={12} strokeWidth={2} className="flex-shrink-0" aria-hidden />
        <span
          dir="auto"
          className={
            streaming
              ? 'bg-[linear-gradient(90deg,rgb(var(--fg-tertiary))_0%,rgb(var(--fg-primary))_50%,rgb(var(--fg-tertiary))_100%)] bg-[length:200%_100%] bg-clip-text text-transparent animate-shimmer'
              : ''
          }
        >
          {label}
        </span>
        <ChevronRight
          size={11}
          strokeWidth={2.5}
          className={`flex-shrink-0 transition-transform duration-fast ease-tool ${expanded ? 'rotate-90' : ''}`}
        />
      </button>
      {expanded && (
        <div
          dir="auto"
          className="mx-1 mt-0.5 max-h-64 overflow-y-auto whitespace-pre-wrap break-words rounded-sm border border-line bg-surface-raised/60 px-2.5 py-1.5 text-xs text-fg-muted"
        >
          {text || '…'}
        </div>
      )}
    </div>
  );
}
