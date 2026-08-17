import { isPersistentAutomationSession } from './sessionNames';

export interface WsKeepaliveSession {
  turnRunning?: boolean;
}

/** Sessions that should hold an open WebSocket to the bridge. */
export function collectWsKeepOpen(
  activeSession: string | null,
  sessions: Record<string, WsKeepaliveSession>,
): string[] {
  const keep = new Set<string>();
  if (activeSession) keep.add(activeSession);
  for (const [name, session] of Object.entries(sessions)) {
    if (session.turnRunning) keep.add(name);
    if (isPersistentAutomationSession(name)) keep.add(name);
  }
  return [...keep];
}
