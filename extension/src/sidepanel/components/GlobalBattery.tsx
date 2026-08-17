/**
 * GlobalBattery — the active Claude 5-hour usage block, click for full breakdown.
 *
 * The bar shows how much of the 5-hour limit REMAINS (drains as you use it),
 * using the official utilization from /api/oauth/usage when available, with a
 * time-based fallback. The label shows "N% · Xh Ym" (used % · time to reset).
 * Clicking opens UsageModal with the weekly limits and token/cost detail.
 */
import { useEffect, useState } from 'react';
import { Clock } from 'lucide-react';
import type { QuotaInfo } from '../bridge';
import { UsageModal } from './UsageModal';

const BLOCK_MS = 5 * 60 * 60 * 1000; // Claude usage blocks are 5 hours

function formatRemaining(ms: number): string {
  const totalMin = Math.max(0, Math.round(ms / 60000));
  const h = Math.floor(totalMin / 60);
  const m = totalMin % 60;
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

interface GlobalBatteryProps {
  quota: QuotaInfo;
}

export function GlobalBattery({ quota }: GlobalBatteryProps) {
  const [now, setNow] = useState(() => Date.now());
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(id);
  }, []);

  const fiveHour = quota.limits?.five_hour;
  const resetIso = fiveHour?.resets_at ?? quota.reset_at;
  if (!quota.available || !resetIso) return null;

  const resetMs = new Date(resetIso).getTime();
  if (Number.isNaN(resetMs)) return null;
  const remainingMs = Math.max(0, resetMs - now);

  // Prefer official utilization; fall back to elapsed-time fraction.
  const used =
    fiveHour?.utilization != null
      ? Math.max(0, Math.min(100, Math.round(fiveHour.utilization)))
      : Math.round((1 - Math.min(1, remainingMs / BLOCK_MS)) * 100);
  const remainingFrac = (100 - used) / 100;

  // Lots of quota left = green, almost spent = red.
  const barColor = remainingFrac <= 0.15 ? 'bg-error' : remainingFrac <= 0.35 ? 'bg-warning' : 'bg-success';
  const textColor = remainingFrac <= 0.15 ? 'text-error' : remainingFrac <= 0.35 ? 'text-warning' : 'text-fg-subtle';

  const resetLabel = new Date(resetMs).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  const tooltip =
    `Claude 5-hour block — ${used}% used, ${formatRemaining(remainingMs)} until reset (at ${resetLabel}).\n` +
    `Click for the full usage breakdown.`;

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        title={tooltip}
        aria-label="Show usage breakdown"
        className="flex items-center gap-1.5 rounded-md px-1 py-0.5 transition-colors duration-fast ease-tool hover:bg-surface-raised"
      >
        <Clock size={11} strokeWidth={2} className={`flex-shrink-0 ${textColor}`} aria-hidden />
        <div className="flex h-3 w-10 items-center overflow-visible">
          <div className="h-2.5 w-9 overflow-hidden rounded-sm border border-line bg-surface-raised">
            <div
              className={`h-full transition-[width] duration-500 ease-out ${barColor}`}
              style={{ width: `${Math.round(remainingFrac * 100)}%` }}
            />
          </div>
          <div className="ml-px h-1.5 w-1 flex-shrink-0 rounded-r-sm border border-line bg-line" />
        </div>
        <span className={`font-mono text-2xs tabular-nums ${textColor}`}>
          {used}% · {formatRemaining(remainingMs)}
        </span>
      </button>
      {open && <UsageModal quota={quota} onClose={() => setOpen(false)} />}
    </>
  );
}
