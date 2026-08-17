/**
 * BrowserContextStrip — linked-tab status or warnings when setup needs attention.
 */
import { AlertTriangle, ExternalLink, Link2, RefreshCw } from 'lucide-react';
import type { BoundTab } from '@/shared/tabBinding';
import { shortTabLabel } from '@/shared/tabBinding';
import type { BrowserStatus } from '../hooks/useBrowserStatus';
import { focusBoundTab } from '../utils/autoBindTab';
import { EXTENSION_DISCONNECTED_BANNER } from '../utils/browserDisconnect';

interface BrowserContextStripProps {
  isSessionConnected: boolean;
  boundTab?: BoundTab | null;
  boundTabStale?: boolean;
  browser: BrowserStatus;
  extensionDisconnected?: boolean;
  onRebind?: () => void;
  onReconnectExtension?: () => void;
}

export function BrowserContextStrip({
  isSessionConnected,
  boundTab,
  boundTabStale = false,
  browser,
  extensionDisconnected = false,
  onRebind,
  onReconnectExtension,
}: BrowserContextStripProps) {
  if (!isSessionConnected) return null;

  if (extensionDisconnected) {
    return (
      <div className="flex shrink-0 items-center gap-2 border-b border-danger/30 bg-danger-subtle/40 px-3 py-1 text-2xs text-danger">
        <AlertTriangle size={11} strokeWidth={2} className="flex-shrink-0" />
        <span className="min-w-0 flex-1">{EXTENSION_DISCONNECTED_BANNER}</span>
        {onReconnectExtension && (
          <button
            type="button"
            onClick={onReconnectExtension}
            className="flex flex-shrink-0 items-center gap-0.5 rounded-sm border border-danger/40 px-1.5 py-0.5 font-medium hover:bg-danger/10"
          >
            <RefreshCw size={10} strokeWidth={2} />
            Reconnect
          </button>
        )}
      </div>
    );
  }

  if (browser.browserReachable === false) {
    return (
      <div className="flex shrink-0 items-center gap-1.5 border-b border-warning/30 bg-warning-subtle/40 px-3 py-1 text-2xs text-warning">
        <AlertTriangle size={11} strokeWidth={2} className="flex-shrink-0" />
        <span className="min-w-0 truncate">
          Browser unreachable — reload the extension or open DevScope in this Chrome profile
        </span>
      </div>
    );
  }

  if (boundTabStale || (boundTab && boundTabStale)) {
    return (
      <div className="flex shrink-0 items-center gap-2 border-b border-danger/30 bg-danger-subtle/40 px-3 py-1 text-2xs text-danger">
        <AlertTriangle size={11} strokeWidth={2} className="flex-shrink-0" />
        <span className="min-w-0 flex-1 truncate">Bound tab was closed — re-bind the page you want to control</span>
        {onRebind && (
          <button
            type="button"
            onClick={onRebind}
            className="flex-shrink-0 rounded-sm border border-danger/40 px-1.5 py-0.5 font-medium hover:bg-danger/10"
          >
            Re-bind
          </button>
        )}
      </div>
    );
  }

  if (!boundTab) {
    return (
      <div className="flex shrink-0 items-center gap-1.5 border-b border-warning/30 bg-warning-subtle/40 px-3 py-1 text-2xs text-warning">
        <AlertTriangle size={11} strokeWidth={2} className="flex-shrink-0" />
        <span className="min-w-0 truncate">
          No tab bound — use the globe pill below or open DevScope from the page you want to control
        </span>
      </div>
    );
  }

  const label = shortTabLabel(boundTab.title, boundTab.url, 48);

  return (
    <div className="flex shrink-0 items-center gap-2 border-b border-signal/25 bg-signal-subtle/30 px-3 py-1 text-2xs">
      <Link2 size={11} strokeWidth={2} className="flex-shrink-0 text-signal" />
      <span className="min-w-0 flex-1 truncate text-fg-muted">
        <span className="font-medium text-signal">Linked</span>
        {' · '}
        {label}
      </span>
      <button
        type="button"
        title="Switch to the linked tab"
        onClick={() => void focusBoundTab(boundTab)}
        className="flex flex-shrink-0 items-center gap-0.5 rounded-sm border border-line px-1.5 py-0.5 font-medium text-fg-muted transition-colors hover:border-signal/40 hover:text-signal"
      >
        <ExternalLink size={10} strokeWidth={2} />
        Go to tab
      </button>
    </div>
  );
}
