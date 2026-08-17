/**
 * UsageModal — the full Claude usage breakdown, opened by clicking the battery.
 *
 * Mirrors the `claude /usage` screen: official utilization for the 5-hour block
 * and the weekly limits (from /api/oauth/usage), plus this block's token/cost
 * spend (from ccusage). All data arrives pre-merged on the QuotaInfo.
 */
import { useEffect } from 'react';
import { X } from 'lucide-react';
import type { QuotaInfo, UsageLimit } from '../bridge';

interface UsageModalProps {
  quota: QuotaInfo;
  onClose: () => void;
}

const ROWS: { key: string; label: string }[] = [
  { key: 'five_hour', label: 'Current session (5h)' },
  { key: 'seven_day', label: 'Current week — all models' },
  { key: 'seven_day_sonnet', label: 'Current week — Sonnet' },
  { key: 'seven_day_opus', label: 'Current week — Opus' },
];

function barColor(util: number): string {
  if (util >= 85) return 'bg-error';
  if (util >= 65) return 'bg-warning';
  return 'bg-success';
}

function formatReset(iso?: string): string {
  if (!iso) return '';
  const ms = new Date(iso).getTime();
  if (Number.isNaN(ms)) return '';
  const d = new Date(ms);
  const time = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  const day = d.toLocaleDateString([], { month: 'short', day: 'numeric' });
  const isToday = new Date().toDateString() === d.toDateString();
  return isToday ? `resets ${time}` : `resets ${day}, ${time}`;
}

function formatTokens(n?: number): string {
  if (!n) return '0';
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1000) return `${(n / 1000).toFixed(0)}k`;
  return String(n);
}

function LimitRow({ label, limit }: { label: string; limit: UsageLimit }) {
  const util = Math.max(0, Math.min(100, Math.round(limit.utilization)));
  return (
    <div className="mb-3">
      <div className="mb-1 flex items-baseline justify-between">
        <span className="text-xs font-medium text-fg">{label}</span>
        <span className="font-mono text-2xs tabular-nums text-fg-subtle">{util}% used</span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-sm bg-surface-raised">
        <div className={`h-full ${barColor(util)}`} style={{ width: `${util}%` }} />
      </div>
      <span className="mt-0.5 block text-2xs text-fg-subtle">{formatReset(limit.resets_at)}</span>
    </div>
  );
}

export function UsageModal({ quota, onClose }: UsageModalProps) {
  useEffect(() => {
    function onKey(e: globalThis.KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const limits = quota.limits ?? {};
  const rows = ROWS.filter((r) => limits[r.key]);
  const extra = quota.extra_usage;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ backdropFilter: 'blur(4px)', backgroundColor: 'rgba(0,0,0,0.4)' }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="w-[320px] rounded-lg border border-line bg-surface-overlay p-5 shadow-modal dark:shadow-modal-dark">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-fg">Claude usage</h2>
          <button
            onClick={onClose}
            aria-label="Close"
            className="rounded-md p-1 text-fg-subtle transition-colors duration-fast ease-tool hover:bg-surface-raised hover:text-fg"
          >
            <X size={14} strokeWidth={2.5} />
          </button>
        </div>

        {rows.length === 0 ? (
          <p className="text-xs text-fg-muted">Usage limits unavailable.</p>
        ) : (
          rows.map((r) => <LimitRow key={r.key} label={r.label} limit={limits[r.key]} />)
        )}

        {(quota.total_tokens != null || quota.cost_usd != null) && (
          <div className="mt-2 border-t border-line pt-3">
            <div className="flex items-center justify-between text-xs">
              <span className="text-fg-muted">This session block</span>
              <span className="font-mono text-fg-subtle">
                {formatTokens(quota.total_tokens)} tokens
                {quota.cost_usd != null && ` · $${quota.cost_usd.toFixed(2)}`}
              </span>
            </div>
          </div>
        )}

        <p className="mt-3 text-2xs leading-snug text-fg-subtle">
          {extra?.is_enabled
            ? 'Usage credits are on.'
            : 'Usage credits are off.'}{' '}
          Shared across all sessions on this machine.
        </p>
      </div>
    </div>
  );
}
