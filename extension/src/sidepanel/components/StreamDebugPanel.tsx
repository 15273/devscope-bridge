/**
 * StreamDebugPanel — live turn/WS/transcript diagnostics for stuck chat streams.
 * Collapsed by default to a one-line summary; expand for full grid + event log.
 */
import { useEffect, useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import type { SessionState } from '../store/sessionStore';
import { hasEmptyStreamingAssistant } from '../utils/transcriptSync';
import {
  clearStreamDebug,
  formatDebugAge,
  subscribeStreamDebug,
  type StreamDebugEvent,
} from '../utils/streamDebug';

interface Props {
  session: SessionState;
}

function latestOf(events: StreamDebugEvent[], kind: StreamDebugEvent['kind']): StreamDebugEvent | undefined {
  for (let i = events.length - 1; i >= 0; i--) {
    if (events[i].kind === kind) return events[i];
  }
  return undefined;
}

function stuckHintFor(session: SessionState, emptyStream: boolean, streaming: boolean): string {
  if (emptyStream && session.turnRunning !== true) {
    return 'STUCK? empty spinner + bridge idle';
  }
  if (emptyStream && session.turnRunning) {
    return 'waiting: empty spinner, turn running';
  }
  if (streaming && !session.turnRunning) {
    return 'STUCK? streaming UI, turnRunning=false';
  }
  if (session.activity === 'Thinking…' && !streaming && !session.turnRunning) {
    return 'STUCK? Thinking… leftover';
  }
  return 'ok';
}

export function StreamDebugPanel({ session }: Props) {
  const [events, setEvents] = useState<StreamDebugEvent[]>([]);
  const [now, setNow] = useState(Date.now());
  const [expanded, setExpanded] = useState(false);

  useEffect(() => subscribeStreamDebug(setEvents), []);
  useEffect(() => {
    if (!expanded) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [expanded]);

  const mine = events.filter((e) => e.session === session.name || e.session === '*');
  const lastWs = latestOf(mine, 'ws_frame');
  const lastMerge = latestOf(mine, 'merge');
  const lastSync = latestOf(mine, 'sync');
  const lastTurn = latestOf(mine, 'turn');
  const emptyStream = hasEmptyStreamingAssistant(session);
  const streaming = session.messages.some((m) => m.role === 'assistant' && m.isStreaming);
  const stuckHint = stuckHintFor(session, emptyStream, streaming);
  const isStuck = stuckHint.startsWith('STUCK');
  const Chevron = expanded ? ChevronDown : ChevronRight;

  return (
    <div className="border-b border-amber-500/40 bg-amber-500/10 px-2 py-1 font-mono text-2xs text-fg-muted">
      <div className="flex items-center gap-1.5">
        <button
          type="button"
          className="flex min-w-0 flex-1 items-center gap-1 text-left hover:text-fg"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
        >
          <Chevron size={12} strokeWidth={2.25} className="shrink-0 text-amber-700 dark:text-amber-300" />
          <span className="shrink-0 font-semibold text-amber-700 dark:text-amber-300">Stream debug</span>
          <span className={session.isConnected ? 'text-green-600' : 'text-red-600'}>
            {session.isConnected ? 'WS' : 'WS↓'}
          </span>
          <span className="text-fg-subtle">·</span>
          <span className={`min-w-0 truncate ${isStuck ? 'text-red-600' : 'text-fg-subtle'}`}>
            {stuckHint}
          </span>
        </button>
        {expanded && (
          <button
            type="button"
            className="shrink-0 rounded border border-line px-1.5 py-0.5 text-2xs hover:bg-surface-overlay"
            onClick={() => clearStreamDebug()}
          >
            Clear
          </button>
        )}
      </div>

      {expanded && (
        <div className="mt-1.5 space-y-1">
          <div className="grid grid-cols-2 gap-x-3 gap-y-0.5">
            <span>WS connected</span>
            <span className={session.isConnected ? 'text-green-600' : 'text-red-600'}>
              {session.isConnected ? 'yes' : 'NO'}
            </span>
            <span>turnRunning</span>
            <span>{String(session.turnRunning ?? false)}</span>
            <span>isStreaming</span>
            <span className={emptyStream ? 'text-red-600' : undefined}>
              {streaming ? (emptyStream ? 'yes (EMPTY)' : 'yes') : 'no'}
            </span>
            <span>activity</span>
            <span className="truncate">{session.activity ?? '—'}</span>
            <span>hint</span>
            <span className={isStuck ? 'text-red-600' : 'text-fg'}>{stuckHint}</span>
            <span>last WS</span>
            <span className="truncate">
              {lastWs ? `${lastWs.message} (${formatDebugAge(lastWs.ts, now)})` : '—'}
            </span>
            <span>last merge</span>
            <span className="truncate">
              {lastMerge ? `${lastMerge.message} (${formatDebugAge(lastMerge.ts, now)})` : '—'}
            </span>
            <span>last sync</span>
            <span className="truncate">
              {lastSync ? `${lastSync.message} (${formatDebugAge(lastSync.ts, now)})` : '—'}
            </span>
            <span>last turn evt</span>
            <span className="truncate">
              {lastTurn ? `${lastTurn.message} (${formatDebugAge(lastTurn.ts, now)})` : '—'}
            </span>
          </div>
          <div className="max-h-24 overflow-y-auto rounded border border-line/60 bg-surface-raised/80 px-1.5 py-1">
            {mine.length === 0 ? (
              <div className="text-fg-subtle">No events yet — send a message or wait for poll.</div>
            ) : (
              [...mine].reverse().slice(0, 24).map((e, i) => (
                <div key={`${e.ts}-${i}`} className="truncate leading-relaxed">
                  <span className="text-fg-subtle">{formatDebugAge(e.ts, now)}</span>{' '}
                  <span className="text-amber-700 dark:text-amber-300">{e.kind}</span> {e.message}
                </div>
              ))
            )}
          </div>
          <p className="text-fg-subtle">
            Console filter: <code>DevScope:stream</code>
          </p>
        </div>
      )}
    </div>
  );
}
