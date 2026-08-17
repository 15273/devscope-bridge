/**
 * OrchestratorSettings — tick interval, worker cap, quota-based throttle.
 */
import { useCallback, useEffect, useState } from 'react';
import { Loader2 } from 'lucide-react';
import {
  fetchOrchestratorConfig,
  patchOrchestratorConfig,
  type OrchestratorConfig,
} from '../bridge';
import { TokenAuditPanel } from './TokenAuditPanel';

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="mb-2 text-2xs font-semibold uppercase tracking-wider text-fg-subtle">{children}</h3>
  );
}

const THROTTLE_HINT: Record<string, string> = {
  full_speed: 'כל ה-workers המוגדרים פעילים',
  mid_utilization: 'מכסה מופחתת ל-50% כש-quota מעל mid',
  high_utilization: 'worker יחיד כש-quota מעל high',
  throttle_disabled: 'ללא התאמה אוטומטית לפי quota',
};

export function OrchestratorSettings() {
  const [config, setConfig] = useState<OrchestratorConfig | null>(null);
  const [effectiveWorkers, setEffectiveWorkers] = useState<number | null>(null);
  const [throttleReason, setThrottleReason] = useState('');
  const [utilization, setUtilization] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const load = useCallback(async () => {
    const data = await fetchOrchestratorConfig();
    if (!data) return;
    setConfig({ ...data.config, paused: data.config.paused ?? false });
    setEffectiveWorkers(data.runtime.effective_max_workers);
    setThrottleReason(data.runtime.throttle.reason);
    setUtilization(data.runtime.throttle.utilization);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const save = useCallback(async () => {
    if (!config) return;
    setSaving(true);
    const result = await patchOrchestratorConfig(config);
    setSaving(false);
    if (!result) return;
    setConfig(result.config);
    setEffectiveWorkers(result.runtime.effective_max_workers);
    setThrottleReason(result.runtime.throttle.reason);
    setUtilization(result.runtime.throttle.utilization);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }, [config]);

  if (!config) {
    return (
      <section>
        <SectionTitle>סוכן אוטונומי (Orchestrator)</SectionTitle>
        <p className="text-xs text-fg-subtle">טוען…</p>
      </section>
    );
  }

  return (
    <section dir="rtl">
      <SectionTitle>סוכן אוטונומי (Orchestrator)</SectionTitle>
      <p className="mb-3 text-xs text-fg-muted">
        קצב dispatch של workers — מתאים אוטומטית לפי שימוש Claude כש-throttle פעיל.
      </p>
      <p className="mb-3 rounded-md bg-surface-raised px-2 py-1.5 text-2xs text-fg-muted">
        ניקוי אוטומטי פעיל: reset ל-mom/mgr לפני כל tick, מחיקת workers ישנים, הגבלת תור ATS,
        pause אוטומטי כש-quota גבוה + תור גדול (כל 5 דק).
      </p>

      <div className="space-y-3 rounded-lg border border-line bg-surface-overlay/40 p-3">
        <label className="block">
          <span className="mb-1 block text-xs text-fg-muted">מרווח tick (שניות)</span>
          <input
            type="number"
            min={30}
            max={3600}
            value={config.tick_seconds}
            onChange={(e) =>
              setConfig({ ...config, tick_seconds: Number(e.target.value) || 720 })
            }
            className="w-full rounded-md border border-line bg-surface-overlay px-2 py-1.5 text-xs text-fg"
          />
          <span className="mt-0.5 block text-2xs text-fg-subtle">
            ≈ {Math.round(config.tick_seconds / 60)} דקות בין מחזורי orchestrator
          </span>
        </label>

        <label className="block">
          <span className="mb-1 block text-xs text-fg-muted">מקסימום workers במקביל</span>
          <input
            type="number"
            min={1}
            max={16}
            value={config.max_workers}
            onChange={(e) =>
              setConfig({ ...config, max_workers: Number(e.target.value) || 4 })
            }
            className="w-full rounded-md border border-line bg-surface-overlay px-2 py-1.5 text-xs text-fg"
          />
        </label>

        <label className="flex cursor-pointer items-center gap-2">
          <input
            type="checkbox"
            checked={config.paused}
            onChange={(e) => setConfig({ ...config, paused: e.target.checked })}
            className="rounded border-line"
          />
          <span className="text-xs text-fg">השהה תור (pause) — לא מ dispatch משימות חדשות</span>
        </label>

        <label className="flex cursor-pointer items-center gap-2">
          <input
            type="checkbox"
            checked={config.quota_throttle_enabled}
            onChange={(e) =>
              setConfig({ ...config, quota_throttle_enabled: e.target.checked })
            }
            className="rounded border-line"
          />
          <span className="text-xs text-fg">האטה אוטומטית לפי quota Claude</span>
        </label>

        {config.quota_throttle_enabled && (
          <div className="grid grid-cols-2 gap-2">
            <label className="block">
              <span className="mb-1 block text-2xs text-fg-subtle">האטה בינונית מ-%</span>
              <input
                type="number"
                min={20}
                max={98}
                value={config.quota_mid_utilization}
                onChange={(e) =>
                  setConfig({
                    ...config,
                    quota_mid_utilization: Number(e.target.value) || 60,
                  })
                }
                className="w-full rounded-md border border-line bg-surface-overlay px-2 py-1.5 text-xs"
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-2xs text-fg-subtle">האטה חזקה מ-%</span>
              <input
                type="number"
                min={50}
                max={99}
                value={config.quota_high_utilization}
                onChange={(e) =>
                  setConfig({
                    ...config,
                    quota_high_utilization: Number(e.target.value) || 80,
                  })
                }
                className="w-full rounded-md border border-line bg-surface-overlay px-2 py-1.5 text-xs"
              />
            </label>
          </div>
        )}

        {effectiveWorkers != null && (
          <p className="rounded-md bg-surface-raised px-2 py-1.5 text-2xs text-fg-muted">
            עכשיו: <strong>{effectiveWorkers}</strong> workers אפקטיביים
            {utilization != null && ` · quota ${Math.round(utilization)}%`}
            {' · '}
            {THROTTLE_HINT[throttleReason] ?? throttleReason}
          </p>
        )}

        <button
          type="button"
          onClick={() => void save()}
          disabled={saving}
          className="flex items-center gap-1.5 rounded-md bg-signal px-3 py-1.5 text-xs font-medium text-signal-contrast disabled:opacity-60"
        >
          {saving && <Loader2 size={12} className="animate-spin" />}
          {saved ? 'נשמר' : 'שמור הגדרות orchestrator'}
        </button>

        <TokenAuditPanel />
      </div>
    </section>
  );
}
