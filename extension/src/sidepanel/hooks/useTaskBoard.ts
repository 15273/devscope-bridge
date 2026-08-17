/**
 * useTaskBoard — polls GET /orchestrator/board and listens for WS task events.
 */
import { useCallback, useEffect, useState } from 'react';
import { fetchTaskBoard, type TaskBoardSnapshot } from '../bridge';

const POLL_MS = 5_000;

export function useTaskBoard(enabled: boolean, domain: string | null = null) {
  const [board, setBoard] = useState<TaskBoardSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const snap = await fetchTaskBoard(domain);
    if (!snap) {
      setError('לא ניתן לטעון את לוח המשימות');
      return;
    }
    setError(null);
    setBoard(snap);
    setLoading(false);
  }, [domain]);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    const load = async (): Promise<void> => {
      await refresh();
      if (cancelled) return;
    };
    void load();
    const id = setInterval(() => void refresh(), POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [enabled, refresh]);

  useEffect(() => {
    if (!enabled) return;
    function onMessage(msg: unknown) {
      const m = msg as { kind?: string };
      if (m.kind === 'task_board_event') void refresh();
    }
    chrome.runtime.onMessage.addListener(onMessage);
    return () => chrome.runtime.onMessage.removeListener(onMessage);
  }, [enabled, refresh]);

  return { board, loading, error, refresh };
}
