/**
 * BoundTabPill — shows / changes which browser tab this session controls (all windows).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Globe, ChevronDown } from 'lucide-react';
import type { BoundTab, BrowserTabSummary } from '@/shared/tabBinding';
import { loadBoundTab, shortTabLabel } from '@/shared/tabBinding';
import { bindTabById, listTabsViaBackground } from '../../utils/autoBindTab';
import { AnchorPopover } from './AnchorPopover';

interface BoundTabPillProps {
  sessionName: string;
  onBoundChange?: (tab: BoundTab | null) => void;
}

function windowLabel(focused: boolean, index: number): string {
  const n = index + 1;
  return focused ? `Window ${n} (focused)` : `Window ${n}`;
}

export function BoundTabPill({ sessionName, onBoundChange }: BoundTabPillProps) {
  const [bound, setBound] = useState<BoundTab | null>(null);
  const [stale, setStale] = useState(false);
  const [open, setOpen] = useState(false);
  const [tabs, setTabs] = useState<BrowserTabSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const anchorRef = useRef<HTMLDivElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);

  const refresh = useCallback(async () => {
    const b = await loadBoundTab(sessionName);
    if (b) {
      try {
        await chrome.tabs.get(b.tabId);
        setBound(b);
        setStale(false);
        onBoundChange?.(b);
        return;
      } catch {
        setBound(b);
        setStale(true);
        onBoundChange?.(null);
        return;
      }
    }
    setBound(null);
    setStale(false);
    onBoundChange?.(null);
  }, [sessionName, onBoundChange]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    listTabsViaBackground()
      .then(setTabs)
      .finally(() => setLoading(false));
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node;
      if (anchorRef.current?.contains(t) || popoverRef.current?.contains(t)) return;
      setOpen(false);
    };
    window.addEventListener('mousedown', onDown);
    return () => window.removeEventListener('mousedown', onDown);
  }, [open]);

  const tabsByWindow = useMemo(() => {
    const windowOrder: number[] = [];
    const groups = new Map<number, BrowserTabSummary[]>();
    for (const t of tabs) {
      if (!groups.has(t.windowId)) {
        windowOrder.push(t.windowId);
        groups.set(t.windowId, []);
      }
      groups.get(t.windowId)!.push(t);
    }
    windowOrder.sort((a, b) => {
      const aF = groups.get(a)?.some((t) => t.windowFocused) ? 1 : 0;
      const bF = groups.get(b)?.some((t) => t.windowFocused) ? 1 : 0;
      return bF - aF;
    });
    return windowOrder.map((wid, index) => ({
      windowId: wid,
      label: windowLabel(groups.get(wid)?.some((t) => t.windowFocused) ?? false, index),
      tabs: groups.get(wid) ?? [],
    }));
  }, [tabs]);

  const selectTab = async (tab: BrowserTabSummary) => {
    const next = await bindTabById(sessionName, tab.id);
    if (!next) return;
    setBound(next);
    onBoundChange?.(next);
    setOpen(false);
  };

  const label = stale
    ? 'Tab closed'
    : bound
      ? shortTabLabel(bound.title, bound.url, 28)
      : 'No tab bound';

  return (
    <div ref={anchorRef} className="relative max-w-full">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        title={bound ? (stale ? 'Bound tab was closed — pick a new tab' : bound.url) : 'Choose which browser tab DevScope controls (all Chrome windows)'}
        className={`flex max-w-[140px] items-center gap-1 rounded-sm border px-1.5 py-0.5 text-2xs transition-colors duration-fast ease-tool sm:max-w-[180px] ${
          stale
            ? 'border-danger/40 bg-danger-subtle text-danger'
            : bound
              ? 'border-line text-fg-muted hover:border-signal/40 hover:text-signal'
              : 'border-warning/40 bg-warning-subtle text-warning'
        }`}
      >
        <Globe size={11} strokeWidth={2} />
        <span className="truncate">{label}</span>
        <ChevronDown size={10} strokeWidth={2.5} className="flex-shrink-0 opacity-60" />
      </button>

      <AnchorPopover
        anchorRef={anchorRef}
        popoverRef={popoverRef}
        open={open}
        width={320}
        minWidth={256}
        className="max-h-64 overflow-y-auto rounded-md border border-line bg-surface-raised py-1 shadow-modal dark:shadow-modal-dark"
      >
          <p className="px-2 py-1 text-[10px] uppercase tracking-wider text-fg-subtle">
            All Chrome windows · pick one tab
          </p>
          {loading && (
            <p className="px-2 py-2 text-2xs text-fg-muted">Loading tabs…</p>
          )}
          {!loading && tabs.length === 0 && (
            <p className="px-2 py-2 text-2xs text-fg-muted">No scriptable tabs open.</p>
          )}
          {tabsByWindow.map((group) => (
            <div key={group.windowId}>
              <p className="sticky top-0 bg-surface-raised px-2 py-1 text-[10px] font-medium text-fg-subtle">
                {group.label} · {group.tabs.length} tab{group.tabs.length === 1 ? '' : 's'}
              </p>
              {group.tabs.map((t) => (
                <button
                  key={t.id}
                  type="button"
                  onClick={() => void selectTab(t)}
                  className={`flex w-full flex-col items-start gap-0.5 px-2 py-1.5 text-left text-2xs transition-colors duration-fast ease-tool hover:bg-signal-subtle ${
                    bound?.tabId === t.id ? 'bg-signal-subtle/60' : ''
                  }`}
                >
                  <span className="line-clamp-1 font-medium text-fg">
                    {t.active ? '● ' : ''}{t.title || '(untitled)'}
                  </span>
                  <span className="line-clamp-1 font-mono text-[10px] text-fg-subtle">{t.url}</span>
                </button>
              ))}
            </div>
          ))}
      </AnchorPopover>
    </div>
  );
}
