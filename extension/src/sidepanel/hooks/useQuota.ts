/**
 * useQuota — polls the bridge for the active Claude 5-hour usage block.
 *
 * The bridge runs ccusage (cached) so polling is cheap; we refresh every few
 * minutes and let the battery tick its own countdown from `reset_at` between
 * polls, so the "resets in Xm" stays live without hammering the bridge.
 */
import { useEffect, useState } from 'react';
import { fetchQuota, type QuotaInfo } from '../bridge';

const POLL_MS = 3 * 60 * 1000; // 3 minutes

export function useQuota(enabled: boolean): QuotaInfo | null {
  const [quota, setQuota] = useState<QuotaInfo | null>(null);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;

    const load = async (): Promise<void> => {
      const next = await fetchQuota();
      if (!cancelled) setQuota(next);
    };

    void load();
    const id = setInterval(() => void load(), POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [enabled]);

  return quota;
}
