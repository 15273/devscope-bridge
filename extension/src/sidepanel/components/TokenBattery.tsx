/**
 * TokenBattery — always-visible context-window usage bar.
 * Shows how much of the 200k token context window is occupied,
 * colored green → yellow → red as it fills up.
 */

const CONTEXT_WINDOW = 200_000;

function formatK(n: number): string {
  return n >= 1000 ? `${(n / 1000).toFixed(0)}k` : String(n);
}

interface TokenBatteryProps {
  contextTokens: number;
}

export function TokenBattery({ contextTokens }: TokenBatteryProps) {
  const pct = Math.min(1, contextTokens / CONTEXT_WINDOW);
  const pctDisplay = Math.round(pct * 100);
  const remaining = Math.max(0, CONTEXT_WINDOW - contextTokens);

  const barColor =
    pct >= 0.85
      ? 'bg-error'
      : pct >= 0.6
        ? 'bg-warning'
        : 'bg-success';

  const textColor =
    pct >= 0.85 ? 'text-error' : pct >= 0.6 ? 'text-warning' : 'text-fg-subtle';

  return (
    <div
      className="flex items-center gap-1.5"
      title={`Context window: ${formatK(contextTokens)} / ${formatK(CONTEXT_WINDOW)} tokens used (${pctDisplay}%). ~${formatK(remaining)} remaining. Resets on /new or /compact.`}
    >
      {/* pill-shaped battery outline */}
      <div className="relative flex h-3 w-10 items-center overflow-visible">
        <div className="h-2.5 w-9 overflow-hidden rounded-sm border border-line bg-surface-raised">
          <div
            className={`h-full transition-[width] duration-500 ease-out ${barColor}`}
            style={{ width: `${pctDisplay}%` }}
          />
        </div>
        {/* nub */}
        <div className="ml-px h-1.5 w-1 flex-shrink-0 rounded-r-sm border border-line bg-line" />
      </div>
      <span className={`font-mono text-2xs tabular-nums ${textColor}`}>
        {pctDisplay}%
      </span>
    </div>
  );
}
