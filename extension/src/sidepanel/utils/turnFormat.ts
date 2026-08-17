/**
 * Pure formatters shared by TurnFooter and ThinkingBlock — framework-free so
 * they can be unit-tested directly without any component rendering.
 */

/** "3200" (ms) -> "3.2s" — always one decimal place. */
export function formatDuration(durationMs: number): string {
  return `${(durationMs / 1000).toFixed(1)}s`;
}

/** Abbreviates with a "k" suffix at >= 1000; leaves smaller counts as-is. */
export function formatTokenCount(n: number): string {
  return n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n);
}

/**
 * "claude-sonnet-5" -> "sonnet-5" — drops the vendor prefix, keeps the rest.
 * Returns null for a missing/empty model so callers can hide that segment.
 */
export function shortModelName(model?: string | null): string | null {
  if (!model) return null;
  return model.startsWith('claude-') ? model.slice('claude-'.length) : model;
}

/** "חשב N שניות" — rounds to the nearest second, floored at 1. */
export function formatThinkingDuration(startedAt: number, doneAt: number): string {
  const seconds = Math.max(1, Math.round((doneAt - startedAt) / 1000));
  return `חשב ${seconds} שניות`;
}
