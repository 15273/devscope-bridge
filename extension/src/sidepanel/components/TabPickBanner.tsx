/**
 * TabPickBanner — ask user to pick a tab when auto-bind finds multiple matches.
 */
import { Globe } from 'lucide-react';
import type { BrowserTabSummary } from '@/shared/tabBinding';
import { shortTabLabel } from '@/shared/tabBinding';

interface TabPickBannerProps {
  reason: string;
  hintUrl?: string;
  candidates: BrowserTabSummary[];
  onPick: (tabId: number) => void;
  onDismiss: () => void;
}

export function TabPickBanner({
  reason,
  hintUrl,
  candidates,
  onPick,
  onDismiss,
}: TabPickBannerProps) {
  return (
    <div className="border-b border-warning/30 bg-warning-subtle px-3 py-2">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <p className="text-xs font-medium text-warning">{reason}</p>
          {hintUrl && (
            <p className="mt-0.5 truncate font-mono text-2xs text-fg-muted">{hintUrl}</p>
          )}
        </div>
        <button
          type="button"
          onClick={onDismiss}
          className="flex-shrink-0 text-2xs text-fg-subtle hover:text-fg"
        >
          Dismiss
        </button>
      </div>
      <div className="mt-2 space-y-1">
        {candidates.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => onPick(t.id)}
            className="flex w-full items-center gap-2 rounded-sm border border-line bg-surface px-2 py-1.5 text-left text-2xs transition-colors duration-fast ease-tool hover:border-signal/40 hover:bg-surface-overlay"
          >
            <Globe size={12} className="flex-shrink-0 text-signal" />
            <span className="min-w-0 flex-1 truncate text-fg">
              {shortTabLabel(t.title, t.url, 48)}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
