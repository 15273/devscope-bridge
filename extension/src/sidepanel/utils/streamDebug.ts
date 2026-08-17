/**
 * streamDebug — realtime ring-buffer + console feed for diagnosing stuck chat
 * streams (missed WS chunks, idle turn, transcript backfill).
 */
export type StreamDebugKind =
  | 'ws_frame'
  | 'poll'
  | 'merge'
  | 'sync'
  | 'backfill'
  | 'turn'
  | 'ui'
  | 'warn';

export interface StreamDebugEvent {
  ts: number;
  kind: StreamDebugKind;
  session: string;
  message: string;
  detail?: Record<string, unknown>;
}

type Listener = (events: StreamDebugEvent[]) => void;

const MAX_EVENTS = 80;
const events: StreamDebugEvent[] = [];
const listeners = new Set<Listener>();
let enabled = false;

export function setStreamDebugEnabled(on: boolean): void {
  enabled = on;
  if (!on) return;
  streamDebug('ui', '*', 'stream debug enabled');
}

export function isStreamDebugEnabled(): boolean {
  return enabled;
}

export function getStreamDebugEvents(): StreamDebugEvent[] {
  return [...events];
}

export function subscribeStreamDebug(listener: Listener): () => void {
  listeners.add(listener);
  listener(getStreamDebugEvents());
  return () => listeners.delete(listener);
}

function notify(): void {
  const snapshot = getStreamDebugEvents();
  for (const listener of listeners) listener(snapshot);
}

/** Push a debug line (console + in-panel ring buffer when enabled). */
export function streamDebug(
  kind: StreamDebugKind,
  session: string,
  message: string,
  detail?: Record<string, unknown>,
): void {
  if (!enabled) return;
  const event: StreamDebugEvent = {
    ts: Date.now(),
    kind,
    session,
    message,
    detail,
  };
  events.push(event);
  if (events.length > MAX_EVENTS) events.splice(0, events.length - MAX_EVENTS);

  const prefix = `[DevScope:stream] ${kind} ${session}`;
  if (detail) console.log(prefix, message, detail);
  else console.log(prefix, message);

  notify();
}

export function clearStreamDebug(): void {
  events.length = 0;
  notify();
}

export function formatDebugAge(ts: number, now = Date.now()): string {
  const sec = Math.max(0, Math.round((now - ts) / 1000));
  if (sec < 60) return `${sec}s ago`;
  return `${Math.floor(sec / 60)}m ${sec % 60}s ago`;
}
