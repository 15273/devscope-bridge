/**
 * useCockpit — data hook for the WhatsApp Copilot.
 *
 * Polls /wa/cockpit/nudges every 30 s. Loads settings on mount.
 * Exposes optimistic mutations: handled/mute remove the card immediately;
 * send also removes the card on success. On network error the list is refetched
 * to restore truth.
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import type { Agent, AgentMode } from '@/shared/frames';
import { BRIDGE_HTTP, getToken, authHeaders } from '../../bridge';

export interface Nudge {
  chat_id: string;
  since_ts: number;         // unix seconds
  state: string;            // 'open'
  name: string;
  is_group: boolean;
  last_msg_preview: string;
}

export interface CockpitSettings {
  threshold_hours: number;
  dm_in_scope: boolean;
  group_allowlist: string[];
  blacklist: string[];
  poll_interval_s: number;
}

const DEFAULT_SETTINGS: CockpitSettings = {
  threshold_hours: 3,
  dm_in_scope: true,
  group_allowlist: [],
  blacklist: [],
  poll_interval_s: 300,
};

// ── Fetch helpers ─────────────────────────────────────────────────────────────

async function bridgeGet<T>(path: string): Promise<T> {
  const token = await getToken();
  const res = await fetch(`${BRIDGE_HTTP}${path}`, {
    headers: authHeaders(token),
  });
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

// ── Hook ─────────────────────────────────────────────────────────────────────

export interface ChatHistoryTurn {
  role: 'user' | 'assistant';
  content: string;
}

export interface AskResult {
  answer: string;
  chat_id: string | null;
  chat_name: string | null;
  inbox?: boolean;
  filter?: 'all' | 'dms' | 'groups';
  unread_count?: number;
}

export interface CockpitHealth {
  live: { ok: boolean; session: string | null; error?: string; sample_chats?: number };
  mirror: { chats: number; messages: number };
}

export interface UseCockpitReturn {
  nudges: Nudge[];
  settings: CockpitSettings;
  loading: boolean;
  error: string | null;
  health: CockpitHealth | null;
  draft: (chatId: string) => Promise<string[]>;
  send: (chatId: string, text: string) => Promise<void>;
  markHandled: (chatId: string) => Promise<void>;
  mute: (chatId: string) => Promise<void>;
  saveSettings: (patch: Partial<CockpitSettings>) => Promise<void>;
  refreshHealth: () => Promise<void>;
  ask: (
    question: string,
    opts?: {
      chatId?: string;
      chatName?: string;
      agent?: Agent;
      model?: string | null;
      mode?: AgentMode;
      history?: ChatHistoryTurn[];
    },
  ) => Promise<AskResult | null>;
}

const POLL_MS = 30_000;

export function useCockpit(sessionName: string | null = null): UseCockpitReturn {
  const [nudges, setNudges] = useState<Nudge[]>([]);
  const [settings, setSettings] = useState<CockpitSettings>(DEFAULT_SETTINGS);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [health, setHealth] = useState<CockpitHealth | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchNudges = useCallback(async () => {
    try {
      const data = await bridgeGet<Nudge[]>('/wa/cockpit/nudges');
      setNudges(data);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  const fetchSettings = useCallback(async () => {
    try {
      const data = await bridgeGet<CockpitSettings>('/wa/cockpit/settings');
      setSettings(data);
    } catch {
      // settings failure is non-fatal; defaults suffice
    }
  }, []);

  const refreshHealth = useCallback(async () => {
    try {
      const q = sessionName ? `?session=${encodeURIComponent(sessionName)}` : '';
      const data = await bridgeGet<CockpitHealth>(`/wa/cockpit/health${q}`);
      setHealth(data);
    } catch {
      setHealth(null);
    }
  }, [sessionName]);

  useEffect(() => {
    let mounted = true;
    async function init() {
      setLoading(true);
      await Promise.all([fetchNudges(), fetchSettings(), refreshHealth()]);
      if (mounted) setLoading(false);
    }
    void init();
    intervalRef.current = setInterval(() => {
      void fetchNudges();
    }, POLL_MS);
    return () => {
      mounted = false;
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [fetchNudges, fetchSettings, refreshHealth]);

  // ── Optimistic remove helper ──────────────────────────────────────────────

  const optimisticRemove = useCallback(
    (chatId: string) => {
      setNudges((prev) => prev.filter((n) => n.chat_id !== chatId));
    },
    [],
  );

  // ── Actions ───────────────────────────────────────────────────────────────

  const markHandled = useCallback(
    async (chatId: string) => {
      optimisticRemove(chatId);
      try {
        await bridgePost<unknown>('/wa/cockpit/handled', { chat_id: chatId });
      } catch (e) {
        // restore on error
        setError(e instanceof Error ? e.message : String(e));
        await fetchNudges();
      }
    },
    [optimisticRemove, fetchNudges],
  );

  const mute = useCallback(
    async (chatId: string) => {
      optimisticRemove(chatId);
      try {
        await bridgePost<unknown>('/wa/cockpit/mute', { chat_id: chatId });
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
        await fetchNudges();
      }
    },
    [optimisticRemove, fetchNudges],
  );

  const draft = useCallback(async (chatId: string): Promise<string[]> => {
    const data = await bridgePost<{ candidates: string[] }>('/wa/cockpit/draft', {
      chat_id: chatId,
    });
    return data.candidates;
  }, []);

  const send = useCallback(
    async (chatId: string, text: string) => {
      await bridgePost<unknown>('/wa/cockpit/send', { chat_id: chatId, text });
      optimisticRemove(chatId);
    },
    [optimisticRemove],
  );

  const saveSettings = useCallback(
    async (patch: Partial<CockpitSettings>) => {
      const updated = await bridgePost<CockpitSettings>('/wa/cockpit/settings', patch);
      setSettings(updated);
    },
    [],
  );

  const ask = useCallback(
    async (
      question: string,
      opts?: {
        chatId?: string;
        chatName?: string;
        agent?: Agent;
        model?: string | null;
        mode?: AgentMode;
        history?: ChatHistoryTurn[];
      },
    ): Promise<AskResult | null> => {
      const token = await getToken();
      const payload: Record<string, unknown> = {
        question,
        agent: opts?.agent ?? 'cursor',
      };
      if (opts?.chatId) payload.chat_id = opts.chatId;
      if (opts?.chatName) payload.chat_name = opts.chatName;
      if (sessionName) payload.session = sessionName;
      if (opts?.model) payload.model = opts.model;
      if (opts?.mode) payload.mode = opts.mode;
      if (opts?.history?.length) payload.history = opts.history;
      const res = await fetch(`${BRIDGE_HTTP}/wa/cockpit/ask`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
        body: JSON.stringify(payload),
      });
      const body = (await res.json()) as { ok: boolean; data?: AskResult; error?: string };
      if (!body.ok) {
        throw new Error(body.error ?? 'bridge error');
      }
      return body.data ?? null;
    },
    [sessionName],
  );

  return {
    nudges,
    settings,
    loading,
    error,
    health,
    draft,
    send,
    markHandled,
    mute,
    saveSettings,
    refreshHealth,
    ask,
  };
}
