/**
 * MetaAdsCockpit — campaigns, insights, alerts (Meta Marketing API).
 */
import { useState, useCallback } from 'react';
import { Megaphone, RefreshCw, Pause, Play, DollarSign } from 'lucide-react';
import { CockpitShell } from '../CockpitShell';
import { AiAssistPanel } from '../AiAssistPanel';
import { useMetaAds, type MetaActionPreview, type MetaCampaign, type MetaInsight } from './useMetaAds';
import { ConfirmMetaActionDialog } from './ConfirmMetaActionDialog';

const DATE_PRESETS = [
  { label: '7 ימים', value: 'last_7d' },
  { label: 'היום', value: 'today' },
  { label: '30 יום', value: 'last_30d' },
];

function insightForCampaign(campaignId: string, rows: MetaInsight[]) {
  return rows.find((i) => i.campaign_id === campaignId);
}

export function MetaAdsCockpit() {
  const {
    accounts,
    campaigns,
    insights,
    alerts,
    selectedAccountId,
    setSelectedAccountId,
    selectedCampaignId,
    setSelectedCampaignId,
    health,
    loading,
    error,
    datePreset,
    setDatePreset,
    refreshAll,
    previewStatus,
    applyStatus,
    previewBudget,
    applyBudget,
    markAlertHandled,
    createDailyReportSchedule,
  } = useMetaAds();

  const [pending, setPending] = useState<{
    preview: MetaActionPreview;
    label: string;
    apply: () => Promise<void>;
  } | null>(null);
  const [budgetInput, setBudgetInput] = useState('');
  const [assistMsg, setAssistMsg] = useState('');
  const needsAuth = health && !health.token_configured;

  const selectedCampaign: MetaCampaign | undefined = campaigns.find(
    (c) => c.id === selectedCampaignId,
  );

  const requestPauseToggle = useCallback(
    async (campaign: MetaCampaign) => {
      const next = campaign.status === 'ACTIVE' ? 'PAUSED' : 'ACTIVE';
      const preview = await previewStatus(campaign.id, next);
      setPending({
        preview,
        label: next === 'PAUSED' ? 'השהיה' : 'הפעלה',
        apply: async () => {
          await applyStatus(campaign.id, next);
          await refreshAll();
        },
      });
    },
    [previewStatus, applyStatus, refreshAll],
  );

  const requestBudget = useCallback(async () => {
    if (!selectedCampaign || !budgetInput) return;
    const amount = parseFloat(budgetInput);
    if (Number.isNaN(amount) || amount <= 0) return;
    const preview = await previewBudget(selectedCampaign.id, amount);
    setPending({
      preview,
      label: 'עדכון תקציב',
      apply: async () => {
        await applyBudget(selectedCampaign.id, amount);
        setBudgetInput('');
        await refreshAll();
      },
    });
  }, [selectedCampaign, budgetInput, previewBudget, applyBudget, refreshAll]);

  const listPane = (
    <div className="flex min-h-0 flex-1 flex-col">
      {accounts.length > 1 && (
        <div className="border-b border-line p-2">
          <select
            value={selectedAccountId ?? ''}
            onChange={(e) => setSelectedAccountId(e.target.value || null)}
            className="w-full rounded border border-line bg-surface px-2 py-1 text-2xs text-fg"
          >
            {accounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name || a.id}
              </option>
            ))}
          </select>
        </div>
      )}
      {alerts.length > 0 && (
        <div className="border-b border-line p-2">
          <p className="mb-1 text-2xs font-semibold text-signal">התראות ({alerts.length})</p>
          <ul className="space-y-1">
            {alerts.slice(0, 3).map((a) => (
              <li key={a.id} className="rounded border border-line bg-surface px-2 py-1 text-2xs">
                <div className="font-medium text-fg">{a.title}</div>
                <button
                  type="button"
                  onClick={() => void markAlertHandled(a.id)}
                  className="mt-0.5 text-signal hover:underline"
                >
                  סמן כטופל
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
      <div className="min-h-0 flex-1 overflow-y-auto">
        {loading && campaigns.length === 0 ? (
          <p className="p-2 text-2xs text-fg-muted">טוען…</p>
        ) : campaigns.length === 0 ? (
          <p className="p-2 text-2xs text-fg-muted">אין קמפיינים.</p>
        ) : (
          <ul>
            {campaigns.map((c) => {
              const ins = insightForCampaign(c.id, insights);
              const active = selectedCampaignId === c.id;
              return (
                <li key={c.id}>
                  <button
                    type="button"
                    onClick={() => setSelectedCampaignId(c.id)}
                    className={[
                      'w-full border-b border-line px-2 py-2 text-start text-2xs',
                      active ? 'bg-signal-subtle text-fg' : 'text-fg-muted hover:bg-surface-overlay',
                    ].join(' ')}
                  >
                    <div className="font-medium">{c.name}</div>
                    <div className="text-fg-subtle">
                      {c.effective_status || c.status}
                      {ins ? ` · ₪${ins.spend.toFixed(0)}` : ''}
                    </div>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );

  const readerPane = (
    <div className="flex min-h-0 flex-1 flex-col p-3">
      {!selectedCampaign ? (
        <p className="text-xs text-fg-muted">בחר קמפיין מהרשימה.</p>
      ) : (
        <>
          <h2 className="text-sm font-semibold text-fg">{selectedCampaign.name}</h2>
          <p className="mt-1 text-2xs text-fg-muted">
            {selectedCampaign.objective} · {selectedCampaign.effective_status}
          </p>
          {(() => {
            const ins = insightForCampaign(selectedCampaign.id, insights);
            if (!ins) return null;
            return (
              <dl className="mt-3 grid grid-cols-2 gap-2 text-2xs">
                <div className="rounded border border-line bg-surface-raised p-2">
                  <dt className="text-fg-subtle">הוצאה</dt>
                  <dd className="text-sm font-semibold text-fg">{ins.spend.toFixed(2)}</dd>
                </div>
                <div className="rounded border border-line bg-surface-raised p-2">
                  <dt className="text-fg-subtle">CTR</dt>
                  <dd className="text-sm font-semibold text-fg">{ins.ctr.toFixed(2)}%</dd>
                </div>
                <div className="rounded border border-line bg-surface-raised p-2">
                  <dt className="text-fg-subtle">CPC</dt>
                  <dd className="text-sm font-semibold text-fg">{ins.cpc.toFixed(2)}</dd>
                </div>
                <div className="rounded border border-line bg-surface-raised p-2">
                  <dt className="text-fg-subtle">קליקים</dt>
                  <dd className="text-sm font-semibold text-fg">{ins.clicks}</dd>
                </div>
              </dl>
            );
          })()}
          <div className="mt-4 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => void requestPauseToggle(selectedCampaign)}
              className="flex items-center gap-1 rounded-md border border-line px-2 py-1 text-2xs text-fg"
            >
              {selectedCampaign.status === 'ACTIVE' ? (
                <Pause size={12} />
              ) : (
                <Play size={12} />
              )}
              {selectedCampaign.status === 'ACTIVE' ? 'השהה' : 'הפעל'}
            </button>
          </div>
          <div className="mt-3 flex items-center gap-2">
            <DollarSign size={14} className="text-fg-subtle" />
            <input
              type="number"
              min="1"
              step="1"
              value={budgetInput}
              onChange={(e) => setBudgetInput(e.target.value)}
              placeholder="תקציב יומי"
              className="w-24 rounded border border-line bg-surface px-2 py-1 text-2xs"
            />
            <button
              type="button"
              onClick={() => void requestBudget()}
              className="rounded-md bg-surface-overlay px-2 py-1 text-2xs text-fg"
            >
              עדכן תקציב
            </button>
          </div>
        </>
      )}
    </div>
  );

  const assistPane = (
    <div className="flex flex-1 flex-col">
      <AiAssistPanel
        actions={[
          {
            label: 'דוח יומי (schedule)',
            onClick: () => {
              const aid = selectedAccountId || accounts[0]?.id;
              if (!aid) {
                setAssistMsg('בחר חשבון פרסום.');
                return;
              }
              void createDailyReportSchedule(aid).then(() => {
                setAssistMsg('Schedule נוצר — ראה בלוח משימות.');
              });
            },
          },
          { label: 'רענן', onClick: () => void refreshAll() },
        ]}
      />
      {assistMsg && <p className="px-2 pb-2 text-2xs text-fg-muted">{assistMsg}</p>}
    </div>
  );

  return (
    <div dir="rtl" className="flex min-h-0 flex-1 flex-col overflow-hidden">
      <div className="flex shrink-0 items-center justify-between border-b border-line bg-surface-raised px-3 py-2">
        <div className="flex items-center gap-2 text-sm font-semibold text-fg">
          <Megaphone size={16} className="text-signal" />
          פרסום
          {alerts.length > 0 && (
            <span className="rounded-full bg-signal px-1.5 py-0.5 text-2xs text-signal-contrast">
              {alerts.length}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1">
          {DATE_PRESETS.map((p) => (
            <button
              key={p.value}
              type="button"
              onClick={() => setDatePreset(p.value)}
              className={[
                'rounded px-1.5 py-0.5 text-2xs',
                datePreset === p.value
                  ? 'bg-signal text-signal-contrast'
                  : 'text-fg-muted hover:bg-surface-overlay',
              ].join(' ')}
            >
              {p.label}
            </button>
          ))}
          <button
            type="button"
            onClick={() => void refreshAll()}
            className="flex h-7 w-7 items-center justify-center rounded-md text-fg-muted hover:text-fg"
            aria-label="רענן"
          >
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          </button>
        </div>
      </div>

      {needsAuth && (
        <div className="mx-3 mt-3 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-fg">
          חיבור Meta Ads נדרש. הרץ:
          <code className="mt-1 block break-all rounded bg-surface px-2 py-1 text-2xs">
            FACEBOOK_APP_ID=... FACEBOOK_APP_SECRET=... python -m
            devscope_bridge.meta_ads.authorize_meta_ads
          </code>
        </div>
      )}

      {error && (
        <div className="mx-3 mt-3 rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-200">
          {error}
        </div>
      )}

      <CockpitShell list={listPane} reader={readerPane} assist={assistPane} />

      {pending && (
        <ConfirmMetaActionDialog
          preview={pending.preview}
          actionLabel={pending.label}
          onConfirm={async () => {
            await pending.apply();
            setPending(null);
          }}
          onCancel={() => setPending(null)}
        />
      )}
    </div>
  );
}
