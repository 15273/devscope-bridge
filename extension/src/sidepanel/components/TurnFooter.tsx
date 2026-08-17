/**
 * TurnFooter — one subtle line summarizing a finished turn's cost/usage.
 * "3.2s · ↓1.2k ↑480 · $0.034 · sonnet-5"
 */
import type { TurnMeta } from '../store/turnSegments';
import { formatDuration, formatTokenCount, shortModelName } from '../utils/turnFormat';

export function TurnFooter({ meta }: { meta: TurnMeta }) {
  const parts: string[] = [
    formatDuration(meta.durationMs),
    `↓${formatTokenCount(meta.inputTokens)} ↑${formatTokenCount(meta.outputTokens)}`,
  ];
  if (meta.costUsd > 0) {
    parts.push(`$${meta.costUsd.toFixed(3)}`);
  }
  const model = shortModelName(meta.model);
  if (model) {
    parts.push(model);
  }

  return (
    <span dir="ltr" className="text-2xs text-fg-subtle">
      {parts.join(' · ')}
    </span>
  );
}
