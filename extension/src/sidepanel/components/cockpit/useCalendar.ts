/**
 * useCalendar — data hook for the Google Calendar cockpit.
 */
import { useState, useEffect, useCallback } from 'react';
import { BRIDGE_HTTP, getToken, authHeaders } from '../../bridge';

export interface CalendarEvent {
  id: string;
  summary: string;
  start: string;
  end: string;
  all_day: boolean;
  location: string;
  meet_link: string | null;
  attendees: string[];
}

export interface FreeSlot {
  start: string;
  end: string;
  duration_minutes: number;
}

export interface EventDraft {
  summary: string;
  start: string;
  end: string;
  description: string;
  location: string;
  attendees: string[];
  add_google_meet: boolean;
}

export interface CalendarHealth {
  token_configured: boolean;
  can_write?: boolean;
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

export function useCalendar() {
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [freeSlots, setFreeSlots] = useState<FreeSlot[]>([]);
  const [health, setHealth] = useState<CalendarHealth | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refreshHealth = useCallback(async () => {
    const data = await bridgeGet<CalendarHealth>('/cal/health');
    setHealth(data);
    return data;
  }, []);

  const refreshEvents = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const h = await refreshHealth();
      if (!h.token_configured) {
        setEvents([]);
        return;
      }
      const res = await fetch(`${BRIDGE_HTTP}/cal/events?limit=40`, {
        headers: authHeaders(await getToken()),
      });
      const body = (await res.json()) as {
        ok: boolean;
        data?: CalendarEvent[];
        error?: string;
      };
      if (!body.ok) throw new Error(body.error ?? 'events failed');
      setEvents(body.data ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [refreshHealth]);

  const loadFreeSlots = useCallback(async () => {
    setError(null);
    try {
      const res = await fetch(
        `${BRIDGE_HTTP}/cal/free-slots?duration_minutes=30&days_ahead=7&count=5`,
        { headers: authHeaders(await getToken()) },
      );
      const body = (await res.json()) as {
        ok: boolean;
        data?: FreeSlot[];
        error?: string;
      };
      if (!body.ok) throw new Error(body.error ?? 'free-slots failed');
      setFreeSlots(body.data ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  const validateDraft = useCallback(async (draft: EventDraft) => {
    await bridgePost<EventDraft>('/cal/draft', draft);
  }, []);

  const createEvent = useCallback(
    async (draft: EventDraft): Promise<CalendarEvent> => {
      const created = await bridgePost<CalendarEvent>('/cal/events/create', draft);
      await refreshEvents();
      return created;
    },
    [refreshEvents],
  );

  useEffect(() => {
    void refreshEvents();
  }, [refreshEvents]);

  return {
    events,
    freeSlots,
    health,
    loading,
    error,
    refreshEvents,
    loadFreeSlots,
    validateDraft,
    createEvent,
  };
}
