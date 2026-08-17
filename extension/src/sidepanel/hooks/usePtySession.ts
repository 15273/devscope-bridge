import { useMemo, useRef, type RefObject } from 'react';
import type { TerminalViewHandle } from '../components/TerminalView';

/** Stable PTY id for terminal-first chat: `chat-{session}` (max 64 chars). */
export function chatTerminalId(sessionName: string): string {
  const raw = `chat-${sessionName}`;
  if (raw.length <= 64 && /^[a-zA-Z0-9_-]+$/.test(raw)) return raw;
  const safe = raw.replace(/[^a-zA-Z0-9_-]/g, '-').slice(0, 64);
  return safe || 'chat-session';
}

export interface PtySessionBinding {
  terminalRef: RefObject<TerminalViewHandle | null>;
  terminalId: string;
  session: string;
}

/**
 * Binds a session to a stable chat PTY (`chat-{session}`) for terminal-first mode.
 * TerminalView remounts when `terminalId` changes (session switch).
 */
export function usePtySession(sessionName: string | null, enabled: boolean): PtySessionBinding | null {
  const terminalRef = useRef<TerminalViewHandle | null>(null);
  const terminalId = useMemo(() => {
    if (!sessionName || !enabled) return null;
    return chatTerminalId(sessionName);
  }, [sessionName, enabled]);

  if (!sessionName || !enabled || !terminalId) return null;

  return {
    terminalRef,
    terminalId,
    session: sessionName,
  };
}
