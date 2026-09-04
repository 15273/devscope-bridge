/**
 * Import local Claude / Codex / Antigravity sessions from disk.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { RefreshCw, X } from 'lucide-react';
import type { DiscoveredLocalSession, LocalSessionSource } from '@/shared/frames';
import { discoverLocalSessions } from '../bridge';
import { relativeTime } from '../utils/relativeTime';

type Vendor = 'claude' | 'codex' | 'antigravity';

const VENDORS: { id: Vendor; label: string }[] = [
  { id: 'claude', label: 'Claude' },
  { id: 'codex', label: 'Codex' },
  { id: 'antigravity', label: 'Antigravity' },
];

const GROUPS: { source: LocalSessionSource; label: string; vendor: Vendor }[] = [
  { source: 'claude_code', label: 'Claude Code', vendor: 'claude' },
  { source: 'desktop_code', label: 'Desktop Code', vendor: 'claude' },
  { source: 'desktop_local', label: 'Desktop מקומי', vendor: 'claude' },
  { source: 'codex', label: 'Codex CLI', vendor: 'codex' },
  { source: 'antigravity_cli', label: 'agy CLI', vendor: 'antigravity' },
  { source: 'antigravity_ide', label: 'Antigravity IDE', vendor: 'antigravity' },
];

interface ImportClaudeSessionsModalProps {
  onImport: (sessionId: string, source: string) => Promise<string>;
  onOpenExisting: (name: string) => void;
  onClose: () => void;
}

export function ImportClaudeSessionsModal({
  onImport,
  onOpenExisting,
  onClose,
}: ImportClaudeSessionsModalProps) {
  const [vendor, setVendor] = useState<Vendor>('claude');
  const [items, setItems] = useState<DiscoveredLocalSession[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      setItems(await discoverLocalSessions(vendor));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to scan sessions');
    } finally {
      setLoading(false);
    }
  }, [vendor]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const grouped = useMemo(() => {
    return GROUPS.filter((g) => g.vendor === vendor)
      .map((g) => ({
        ...g,
        items: items.filter((i) => i.source === g.source),
      }))
      .filter((g) => g.items.length > 0);
  }, [items, vendor]);

  const handleOpen = useCallback(
    async (item: DiscoveredLocalSession) => {
      if (item.already_imported && item.bridge_name) {
        onOpenExisting(item.bridge_name);
        onClose();
        return;
      }
      if (!item.can_resume && !item.seed_summary) return;
      setBusyId(item.session_id);
      setError('');
      try {
        const name = await onImport(item.session_id, item.source);
        onOpenExisting(name);
        onClose();
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : 'Import failed');
      } finally {
        setBusyId(null);
      }
    },
    [onClose, onImport, onOpenExisting],
  );

  const blurb =
    vendor === 'codex'
      ? 'שיחות Codex מ- ~/.codex. פתיחה ממשיכה עם exec resume / app-server.'
      : vendor === 'antigravity'
        ? 'agy CLI ניתן ל-resume. שיחות IDE מיובאות כסיכום אלא אם אותו id נפתח ב-agy.'
        : 'שיחות Claude Code ודסקטופ מקומי. פתיחה ממשיכה את השיחה אצלנו.';

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ backdropFilter: 'blur(4px)', backgroundColor: 'rgba(0,0,0,0.4)' }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="flex max-h-[80vh] w-[420px] flex-col rounded-lg border border-line bg-surface-overlay shadow-modal dark:shadow-modal-dark">
        <div className="flex items-center justify-between px-4 py-3">
          <h2 className="text-sm font-semibold text-fg">סשנים במכונה</h2>
          <div className="flex items-center gap-1">
            <button
              onClick={() => void load()}
              aria-label="Refresh"
              title="רענון"
              className="rounded-md p-1 text-fg-subtle transition-colors duration-fast ease-tool hover:bg-surface-raised hover:text-fg"
            >
              <RefreshCw size={14} strokeWidth={2} className={loading ? 'animate-spin' : ''} />
            </button>
            <button
              onClick={onClose}
              aria-label="Close"
              className="rounded-md p-1 text-fg-subtle transition-colors duration-fast ease-tool hover:bg-surface-raised hover:text-fg"
            >
              <X size={14} strokeWidth={2.5} />
            </button>
          </div>
        </div>
        <div className="mx-4 mb-2 grid grid-cols-3 gap-0.5 rounded-md border border-line p-0.5">
          {VENDORS.map((v) => (
            <button
              key={v.id}
              type="button"
              onClick={() => setVendor(v.id)}
              className={`rounded px-2 py-1 text-2xs font-medium ${
                vendor === v.id ? 'bg-fg text-surface' : 'text-fg-muted hover:text-fg'
              }`}
            >
              {v.label}
            </button>
          ))}
        </div>
        <p className="px-4 pb-2 text-2xs leading-snug text-fg-muted">{blurb}</p>

        {error && (
          <p className="mx-4 mb-2 rounded-md bg-danger-subtle px-3 py-2 text-xs text-danger">{error}</p>
        )}

        <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
          {loading && items.length === 0 ? (
            <p className="px-2 py-6 text-center text-xs text-fg-subtle">סורק…</p>
          ) : grouped.length === 0 ? (
            <p className="px-2 py-6 text-center text-xs text-fg-subtle">לא נמצאו סשנים לייבוא</p>
          ) : (
            grouped.map((group) => (
              <div key={group.source} className="mb-2">
                <div className="px-2 py-1 text-2xs font-semibold uppercase tracking-wider text-fg-subtle">
                  {group.label}
                  <span className="ml-1 tabular-nums">{group.items.length}</span>
                </div>
                {group.items.map((item) => (
                  <DiscoverRow
                    key={`${item.source}-${item.session_id}`}
                    item={item}
                    busy={busyId === item.session_id}
                    onOpen={() => void handleOpen(item)}
                  />
                ))}
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}

function DiscoverRow({
  item,
  busy,
  onOpen,
}: {
  item: DiscoveredLocalSession;
  busy: boolean;
  onOpen: () => void;
}) {
  const project = item.cwd.split('/').filter(Boolean).slice(-1)[0] || item.cwd || 'ללא פרויקט';
  const imported = item.already_imported;
  const canOpen = imported || item.can_resume || Boolean(item.seed_summary);
  const action = imported
    ? 'עבור לסשן'
    : item.can_resume
      ? 'פתח ב-DevScope'
      : 'פתח עם סיכום';

  return (
    <div className="mb-0.5 flex items-center gap-2 rounded-md px-2 py-1.5 hover:bg-surface-raised">
      <div className="min-w-0 flex-1">
        <div className="truncate text-xs font-medium text-fg" title={item.title}>
          {item.title}
        </div>
        <div className="truncate text-2xs text-fg-subtle" title={item.cwd}>
          {project}
          {item.last_used ? ` · ${relativeTime(item.last_used)}` : ''}
        </div>
      </div>
      <button
        type="button"
        disabled={!canOpen || busy}
        onClick={onOpen}
        className="flex-shrink-0 rounded-md bg-signal px-2 py-1 text-2xs font-medium text-signal-contrast transition-colors duration-fast ease-tool hover:bg-signal-hover disabled:opacity-40"
      >
        {busy ? '…' : action}
      </button>
    </div>
  );
}
