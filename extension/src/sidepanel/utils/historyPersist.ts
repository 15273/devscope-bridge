/**
 * historyPersist — debounced, change-scoped writer for the chrome.storage
 * chat-history cache.
 *
 * The naive version of this ("compute a persist key for every session on every
 * store commit, write when it changed") measured at ~50% of the side panel's
 * total main-thread time — at idle as well as while streaming. Two reasons:
 *
 *  1. `computePersistKey` concatenates every message's full text, so its cost
 *     is O(total transcript bytes). Running it for EVERY session on every
 *     commit means re-serializing every transcript the panel has ever opened,
 *     many times a second.
 *  2. The session-list poll rebuilds every session object (`{...existing}`)
 *     each tick, so "the store changed" is true constantly even when no
 *     message moved.
 *
 * The messages array itself, however, is only replaced when messages actually
 * change — the poll's object spread carries the same array reference through.
 * So a reference compare is an exact, O(1) "did this session's transcript
 * change" test, and the expensive key is only needed once per debounce window
 * on the one session that moved.
 *
 * This is a crash-recovery cache, not a live mirror — the bridge JSONL
 * transcript is authoritative — so a trailing debounce costs nothing real.
 */
import type { ChatMessage } from '../store/sessionStore';
import { computePersistKey } from './persistKey';

export const PERSIST_DEBOUNCE_MS = 600;

/** Minimal shape this module needs from a session — keeps it testable. */
export interface PersistableSession {
  messages: ChatMessage[];
  isLoadingHistory: boolean;
}

export interface HistoryPersisterOptions {
  /** Write one session's history. Errors are the caller's to swallow. */
  save: (name: string, messages: ChatMessage[]) => void;
  /** Current messages for a session at flush time (may differ from observe time). */
  readMessages: (name: string) => ChatMessage[] | undefined;
  delayMs?: number;
  schedule?: (cb: () => void, ms: number) => number;
  cancel?: (handle: number) => void;
}

export interface HistoryPersister {
  /** Note the current session map; arms a trailing write for any that changed. */
  observe(sessions: Record<string, PersistableSession>): void;
  /** Write every armed session immediately (call on unmount). */
  flush(): void;
}

export function createHistoryPersister(options: HistoryPersisterOptions): HistoryPersister {
  const {
    save,
    readMessages,
    delayMs = PERSIST_DEBOUNCE_MS,
    schedule = (cb, ms) => window.setTimeout(cb, ms),
    cancel = (handle) => window.clearTimeout(handle),
  } = options;

  const seenMessages: Record<string, ChatMessage[]> = {};
  const writtenKeys: Record<string, string> = {};
  const timers = new Map<string, number>();
  const primed = new Set<string>();

  function writeNow(name: string): void {
    timers.delete(name);
    const messages = readMessages(name);
    if (!messages) return;
    const key = computePersistKey(messages);
    if (writtenKeys[name] === key) return;
    writtenKeys[name] = key;
    save(name, messages);
  }

  function observe(sessions: Record<string, PersistableSession>): void {
    for (const [name, session] of Object.entries(sessions)) {
      if (session.isLoadingHistory) continue;
      if (seenMessages[name] === session.messages) continue;
      seenMessages[name] = session.messages;
      // First sight of a session that has finished loading: whatever it holds
      // came straight out of this same cache (or it is brand new and empty).
      // Writing it back would copy every stored transcript onto itself the
      // moment the panel opens — tens of MB of chrome.storage traffic for no
      // change at all. Remember it, write nothing.
      if (!primed.has(name)) {
        primed.add(name);
        continue;
      }
      if (timers.has(name)) continue;
      timers.set(name, schedule(() => writeNow(name), delayMs));
    }
  }

  function flush(): void {
    for (const [name, handle] of [...timers.entries()]) {
      cancel(handle);
      writeNow(name);
    }
  }

  return { observe, flush };
}
