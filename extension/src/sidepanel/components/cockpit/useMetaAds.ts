/**
 * useMetaAds — data hook for Meta Ads cockpit (/meta/*).
 */
import { useState, useEffect, useCallback } from 'react';
import { BRIDGE_HTTP, getToken, authHeaders } from '../../bridge';

export interface MetaAdAccount {
  id: string;
  name: string;
  account_id?: string;
  currency?: string;
}

export interface MetaCampaign {
  id: string;
  name: string;
  status?: string;
  effective_status?: string;
  objective?: string;
  daily_budget?: number | null;
  lifetime_budget?: number | null;
}

export interface MetaInsight {
  campaign_id?: string;
  campaign_name?: string;
  spend: number;
  impressions: number;
  clicks: number;
  ctr: number;
  cpc: number;
  cpm: number;
}

export interface MetaAlert {
  id: number;
  kind: string;
  title: string;
  detail?: string;
  metric: string;
  value: number;
  threshold: number;
}

export interface MetaHealth {
  token_configured: boolean;
  default_ad_account_id?: string | null;
}

export interface MetaActionPreview {
  campaign_id: string;
  before: MetaCampaign;
  after: MetaCampaign;
  dry_run: boolean;
  daily_budget_cents?: number;
}

async function bridgeGet<T>(path: string): Promise<T> {
  const token = await getToken();
  const res = await fetch(`${BRIDGE_HTTP}${path}`, { headers: authHeaders(token) });
  const body = (await res.json()) as { ok: boolean; data?: T; error?: string };
  if (!body.ok) throw new Error(body.error ?? 'bridge error');
  return body.data as T;
}

async function bridgePost<T>(path: string, payload: unknown): Promise<T> {
  const token = await getToken();
  const res = await fetch(`${BRIDGE_HTTP}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
    body: JSON.stringify(payload),
  });
  const body = (await res.json()) as { ok: boolean; data?: T; error?: string };
  if (!body.ok) throw new Error(body.error ?? 'bridge error');
  return body.data as T;
}

export function useMetaAds() {
  const [accounts, setAccounts] = useState<MetaAdAccount[]>([]);
  const [campaigns, setCampaigns] = useState<MetaCampaign[]>([]);
  const [insights, setInsights] = useState<MetaInsight[]>([]);
  const [alerts, setAlerts] = useState<MetaAlert[]>([]);
  const [selectedAccountId, setSelectedAccountId] = useState<string | null>(null);
  const [selectedCampaignId, setSelectedCampaignId] = useState<string | null>(null);
  const [health, setHealth] = useState<MetaHealth | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [datePreset, setDatePreset] = useState('last_7d');

  const refreshHealth = useCallback(async () => {
    const data = await bridgeGet<MetaHealth>('/meta/health');
    setHealth(data);
    if (data.default_ad_account_id && !selectedAccountId) {
      setSelectedAccountId(data.default_ad_account_id);
    }
    return data;
  }, [selectedAccountId]);

  const refreshAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const h = await refreshHealth();
      if (!h.token_configured) {
        setAccounts([]);
        setCampaigns([]);
        setInsights([]);
        return;
      }
      const accts = await bridgeGet<MetaAdAccount[]>('/meta/accounts');
      setAccounts(accts);
      const aid = selectedAccountId || h.default_ad_account_id || accts[0]?.id;
      if (aid) {
        const camps = await bridgeGet<MetaCampaign[]>(
          `/meta/campaigns?ad_account_id=${encodeURIComponent(aid)}`,
        );
        setCampaigns(camps);
        const ins = await bridgeGet<MetaInsight[]>(
          `/meta/insights?ad_account_id=${encodeURIComponent(aid)}&date_preset=${encodeURIComponent(datePreset)}`,
        );
        setInsights(ins);
      }
      const al = await bridgeGet<MetaAlert[]>('/meta/alerts');
      setAlerts(al);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [refreshHealth, selectedAccountId, datePreset]);

  const previewStatus = useCallback(
    async (campaignId: string, status: 'ACTIVE' | 'PAUSED') =>
      bridgePost<MetaActionPreview>(`/meta/campaigns/${campaignId}/status`, {
        status,
        dry_run: true,
      }),
    [],
  );

  const applyStatus = useCallback(
    async (campaignId: string, status: 'ACTIVE' | 'PAUSED') =>
      bridgePost<MetaActionPreview>(`/meta/campaigns/${campaignId}/status`, {
        status,
        dry_run: false,
      }),
    [],
  );

  const previewBudget = useCallback(
    async (campaignId: string, dailyBudget: number) =>
      bridgePost<MetaActionPreview>(`/meta/campaigns/${campaignId}/budget`, {
        daily_budget: dailyBudget,
        dry_run: true,
      }),
    [],
  );

  const applyBudget = useCallback(
    async (campaignId: string, dailyBudget: number) =>
      bridgePost<MetaActionPreview>(`/meta/campaigns/${campaignId}/budget`, {
        daily_budget: dailyBudget,
        dry_run: false,
      }),
    [],
  );

  const markAlertHandled = useCallback(async (alertId: number) => {
    await bridgePost(`/meta/alerts/${alertId}/handled`, {});
    setAlerts((prev) => prev.filter((a) => a.id !== alertId));
  }, []);

  const createDailyReportSchedule = useCallback(async (adAccountId: string) => {
    await bridgePost('/meta/schedules/daily-report', {
      ad_account_id: adAccountId,
      title: 'Meta Ads daily report',
    });
  }, []);

  useEffect(() => {
    void refreshAll();
  }, [refreshAll]);

  return {
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
  };
}
