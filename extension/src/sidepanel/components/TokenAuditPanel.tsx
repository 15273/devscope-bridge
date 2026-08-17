/**
 * TokenAuditPanel — runs GET /usage/audit and shows token burn diagnosis.
 */
import { useCallback, useState } from 'react';
import { Loader2, Search } from 'lucide-react';
import { fetchUsageAudit, type UsageAuditReport } from '../bridge';
import { formatUsageTokens } from '../utils/taskUsageFormat';

function fmtTok(n?: number): string {
  return n != null ? formatUsageTokens(n) : '—';
}

export function TokenAuditPanel() {
  const [report, setReport] = useState<UsageAuditReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(async () => {
    setLoading(true);
    setError(null);
    const data = await fetchUsageAudit();
    setLoading(false);
    if (!data) {
      setError('לא ניתן להריץ audit — ודא שה-bridge רץ');
      return;
    }
    setReport(data);
  }, []);

  const block = report?.active_block;
  const backlog = report?.task_backlog;

  return (
    <div className="mt-4 border-t border-line pt-3" dir="rtl">
      <SectionTitle>אבחון צריכת טוקנים</SectionTitle>
      <p className="mb-2 text-2xs text-fg-muted">
        בודק בלוק 5h, סשנים כבדים, תור משימות והמלצות. לא שורף טוקנים.
      </p>
      <button
        type="button"
        onClick={() => void run()}
        disabled={loading}
        className="mb-3 flex items-center gap-1.5 rounded-md border border-line px-2.5 py-1.5 text-xs text-fg hover:bg-surface-overlay disabled:opacity-60"
      >
        {loading ? <Loader2 size={12} className="animate-spin" /> : <Search size={12} />}
        הרץ audit
      </button>
      {error && <p className="text-xs text-danger">{error}</p>}
      {report && (
        <div className="space-y-2 text-xs">
          {block?.available && (
            <div className="rounded-md bg-surface-raised px-2 py-1.5">
              <p className="font-medium text-fg">בלוק 5 שעות (עכשיו)</p>
              <p className="text-fg-muted">
                {fmtTok(block.total_tokens)} tok · ${block.cost_usd?.toFixed(2) ?? '?'} ·{' '}
                {block.cache_pct_of_total ?? 0}% cache · {block.entries ?? 0} קריאות API
              </p>
            </div>
          )}
          {backlog?.available && (
            <div className="rounded-md bg-surface-raised px-2 py-1.5">
              <p className="font-medium text-fg">תור orchestrator</p>
              <p className="text-fg-muted">
                {backlog.queued ?? 0} בתור · {backlog.in_progress ?? 0} רץ · ATS recovery:{' '}
                {backlog.by_source?.ats_recovery ?? 0}
              </p>
            </div>
          )}
          {report.top_sessions.length > 0 && (
            <div className="rounded-md bg-surface-raised px-2 py-1.5">
              <p className="mb-1 font-medium text-fg">סשנים כבדים (lifetime)</p>
              <ul className="max-h-32 space-y-0.5 overflow-y-auto font-mono text-2xs text-fg-muted">
                {report.top_sessions.slice(0, 8).map((s) => (
                  <li key={s.bridge_session ?? s.total_tokens}>
                    {fmtTok(s.total_tokens)} — {s.bridge_session ?? '(חיצוני)'}
                    {s.is_orchestrator ? ' ⚠' : ''}
                  </li>
                ))}
              </ul>
            </div>
          )}
          <ul className="list-disc space-y-1 pr-4 text-2xs text-warning">
            {report.recommendations.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="mb-2 text-2xs font-semibold uppercase tracking-wider text-fg-subtle">{children}</h3>
  );
}
