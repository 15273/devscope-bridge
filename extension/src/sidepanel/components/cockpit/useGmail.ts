/**
 * useGmail — data hook for the Email cockpit (read-only Gmail via bridge /gm/*).
 */
import { useState, useEffect, useCallback } from 'react';
import { BRIDGE_HTTP, getToken, authHeaders } from '../../bridge';

export interface GmailThreadSummary {
  id: string;
  snippet?: string;
  historyId?: string;
}

export interface GmailMessage {
  from: string;
  date: string;
  snippet: string;
}

export interface GmailThreadDetail {
  id: string;
  subject: string;
  messages: GmailMessage[];
}

export interface GmailHealth {
  token_configured: boolean;
}

async function bridgeGet<T>(path: string): Promise<T> {
  const token = await getToken();
  const res = await fetch(`${BRIDGE_HTTP}${path}`, { headers: authHeaders(token) });
  const body = (await res.json()) as { ok: boolean; data?: T; error?: string };
  if (!body.ok) throw new Error(body.error ?? 'bridge error');
  return body.data as T;
}

export function useGmail(initialQuery = 'in:inbox') {
  const [query, setQuery] = useState(initialQuery);
  const [threads, setThreads] = useState<GmailThreadSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [threadDetail, setThreadDetail] = useState<GmailThreadDetail | null>(null);
  const [health, setHealth] = useState<GmailHealth | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refreshHealth = useCallback(async () => {
    const data = await bridgeGet<GmailHealth>('/gm/health');
    setHealth(data);
    return data;
  }, []);

  const refreshThreads = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const h = await refreshHealth();
      if (!h.token_configured) {
        setThreads([]);
        return;
      }
      const data = await bridgeGet<GmailThreadSummary[]>(
        `/gm/threads?q=${encodeURIComponent(query)}&limit=30`,
      );
      setThreads(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [query, refreshHealth]);

  const loadThread = useCallback(async (threadId: string) => {
    setSelectedId(threadId);
    setDetailLoading(true);
    setError(null);
    try {
      const data = await bridgeGet<GmailThreadDetail>(
        `/gm/thread?thread_id=${encodeURIComponent(threadId)}`,
      );
      setThreadDetail(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setThreadDetail(null);
    } finally {
      setDetailLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshThreads();
  }, [refreshThreads]);

  return {
    query,
    setQuery,
    threads,
    selectedId,
    threadDetail,
    health,
    loading,
    detailLoading,
    error,
    refreshThreads,
    loadThread,
  };
}
