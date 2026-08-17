/**
 * CompactBanner — proactive "session getting expensive" warning (C8).
 * Shown when usage crosses COMPACT_WARN_RATIO of the auto-compact threshold;
 * offers a one-click Compact now (POST /sessions/{name}/compact).
 */
import { Package, X } from 'lucide-react';
import { AUTO_COMPACT_THRESHOLD_TOKENS } from '../utils/workingState';

interface CompactBannerProps {
  tokens: number;
  onCompactNow: () => void;
  onDismiss: () => void;
}

function formatTokens(n: number): string {
  return n >= 1000 ? `${Math.round(n / 1000)}k` : String(n);
}

export function CompactBanner({ tokens, onCompactNow, onDismiss }: CompactBannerProps) {
  return (
    <div className="flex shrink-0 items-center gap-2 border-b border-warning/40 bg-warning-subtle px-3 py-1.5 text-2xs text-warning">
      <Package size={13} strokeWidth={2} aria-hidden className="flex-shrink-0" />
      <span className="min-w-0 flex-1 truncate">
        Session getting expensive ({formatTokens(tokens)} of ~
        {formatTokens(AUTO_COMPACT_THRESHOLD_TOKENS)} tokens before auto-compact)
      </span>
      <button
        onClick={onCompactNow}
        className="flex-shrink-0 rounded-sm border border-warning/50 px-2 py-0.5 font-medium text-warning transition-colors duration-fast ease-tool hover:bg-warning/10"
      >
        Compact now
      </button>
      <button
        onClick={onDismiss}
        title="Dismiss"
        aria-label="Dismiss compact warning"
        className="flex-shrink-0 rounded-sm p-0.5 text-warning/80 transition-colors duration-fast ease-tool hover:text-warning"
      >
        <X size={12} strokeWidth={2.5} />
      </button>
    </div>
  );
}
