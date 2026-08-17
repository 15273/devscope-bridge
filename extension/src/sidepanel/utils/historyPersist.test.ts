import { describe, expect, it, vi } from 'vitest';
import { createHistoryPersister, type PersistableSession } from './historyPersist';
import type { ChatMessage } from '../store/sessionStore';

function msg(id: string, text: string): ChatMessage {
  return { id, role: 'assistant', text, isStreaming: false, isError: false, createdAt: '2026-01-01T00:00:00Z' };
}

function session(messages: ChatMessage[], isLoadingHistory = false): PersistableSession {
  return { messages, isLoadingHistory };
}

/** Deterministic scheduler: collects callbacks, `run()` fires them. */
function fakeClock() {
  const queued = new Map<number, () => void>();
  let next = 1;
  return {
    schedule: (cb: () => void) => {
      const id = next++;
      queued.set(id, cb);
      return id;
    },
    cancel: (id: number) => queued.delete(id),
    run: () => {
      const due = [...queued.values()];
      queued.clear();
      due.forEach((cb) => cb());
    },
    pending: () => queued.size,
  };
}

function harness(sessions: Record<string, PersistableSession>) {
  const clock = fakeClock();
  const save = vi.fn();
  const persister = createHistoryPersister({
    save,
    readMessages: (name) => sessions[name]?.messages,
    schedule: clock.schedule,
    cancel: clock.cancel,
  });
  return { clock, save, persister };
}

describe('createHistoryPersister', () => {
  it('never writes back the history it just loaded from the same cache', () => {
    const sessions = { a: session([msg('1', 'restored from storage')]) };
    const { clock, save, persister } = harness(sessions);

    persister.observe(sessions);
    clock.run();

    expect(save).not.toHaveBeenCalled();
  });

  it('does not write while only the debounce window is open', () => {
    const sessions = { a: session([msg('1', 'hi')]) };
    const { save, persister } = harness(sessions);

    persister.observe(sessions);
    sessions.a = session([msg('1', 'hi there')]);
    persister.observe(sessions);

    expect(save).not.toHaveBeenCalled();
  });

  it('writes once per debounce window no matter how many chunks landed', () => {
    const sessions = { a: session([]) };
    const { clock, save, persister } = harness(sessions);
    persister.observe(sessions);

    // 25 coalesced chunks inside one window — each replaces the messages array.
    for (let i = 0; i < 25; i++) {
      sessions.a = session([msg('1', 'h'.repeat(i + 1))]);
      persister.observe(sessions);
    }
    clock.run();

    expect(save).toHaveBeenCalledTimes(1);
    expect(save).toHaveBeenCalledWith('a', sessions.a.messages);
  });

  it('skips sessions whose messages array is reference-unchanged', () => {
    const sessions = { a: session([]) };
    const { clock, save, persister } = harness(sessions);
    persister.observe(sessions);

    const messages = [msg('1', 'hi')];
    sessions.a = session(messages);
    persister.observe(sessions);
    clock.run();
    expect(save).toHaveBeenCalledTimes(1);

    // Poll rebuilds the session object but keeps the same messages array.
    sessions.a = session(messages);
    persister.observe(sessions);

    expect(clock.pending()).toBe(0);
    expect(save).toHaveBeenCalledTimes(1);
  });

  it('does not rewrite when a rebuilt array holds identical content', () => {
    const sessions = { a: session([]) };
    const { clock, save, persister } = harness(sessions);
    persister.observe(sessions);

    sessions.a = session([msg('1', 'hi')]);
    persister.observe(sessions);
    clock.run();

    sessions.a = session([msg('1', 'hi')]);
    persister.observe(sessions);
    clock.run();

    expect(save).toHaveBeenCalledTimes(1);
  });

  it('never persists a session that is still loading its history', () => {
    const sessions = { a: session([msg('1', 'hi')], true) };
    const { clock, save, persister } = harness(sessions);

    persister.observe(sessions);
    persister.observe(sessions);
    clock.run();

    expect(save).not.toHaveBeenCalled();
  });

  it('flush writes the pending tail immediately', () => {
    const sessions = { a: session([]) };
    const { save, persister } = harness(sessions);
    persister.observe(sessions);

    sessions.a = session([msg('1', 'hi')]);
    persister.observe(sessions);
    persister.flush();

    expect(save).toHaveBeenCalledWith('a', sessions.a.messages);
  });

  it('flush writes the latest messages, not the ones observed when armed', () => {
    const sessions = { a: session([]) };
    const { save, persister } = harness(sessions);
    persister.observe(sessions);

    sessions.a = session([msg('1', 'first')]);
    persister.observe(sessions);
    sessions.a = session([msg('1', 'first and then some more')]);
    persister.observe(sessions);
    persister.flush();

    expect(save).toHaveBeenCalledTimes(1);
    expect(save).toHaveBeenCalledWith('a', sessions.a.messages);
  });

  it('tracks each session independently', () => {
    const sessions = { a: session([]), b: session([]) };
    const { clock, save, persister } = harness(sessions);
    persister.observe(sessions);

    sessions.a = session([msg('1', 'x')]);
    sessions.b = session([msg('2', 'y')]);
    persister.observe(sessions);
    clock.run();
    expect(save).toHaveBeenCalledTimes(2);

    sessions.b = session([msg('2', 'y2')]);
    persister.observe(sessions);
    clock.run();

    expect(save).toHaveBeenCalledTimes(3);
    expect(save).toHaveBeenLastCalledWith('b', sessions.b.messages);
  });
});
