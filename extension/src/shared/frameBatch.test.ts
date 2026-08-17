import { describe, expect, it } from 'vitest';
import { createFrameBatcher } from './frameBatch';

const chunk = (text: string, extra = {}) =>
  ({ type: 'ai_chunk', session: 's', text, turn_id: 't1', block_index: 0, ...extra });

describe('createFrameBatcher', () => {
  it('coalesces same-block ai_chunks within the window', () => {
    const out: any[] = [];
    let pending: (() => void) | null = null;
    const b = createFrameBatcher((f) => out.push(f), 40, (cb) => { pending = cb; });
    b.push(chunk('he'));
    b.push(chunk('llo'));
    expect(out).toHaveLength(0);
    pending!();
    expect(out).toHaveLength(1);
    expect(out[0].text).toBe('hello');
  });

  it('a non-chunk frame flushes buffered chunks first (order preserved)', () => {
    const out: any[] = [];
    const b = createFrameBatcher((f) => out.push(f), 40, () => {});
    b.push(chunk('a'));
    b.push({ type: 'agent_activity', session: 's', label: 'Bash' } as any);
    expect(out.map((f) => f.type)).toEqual(['ai_chunk', 'agent_activity']);
  });

  it('different block_index never merges', () => {
    const out: any[] = [];
    const b = createFrameBatcher((f) => out.push(f), 40, () => {});
    b.push(chunk('a', { block_index: 0 }));
    b.push(chunk('b', { block_index: 2 }));
    b.flush();
    expect(out).toHaveLength(2);
  });

  it('thinking chunks coalesce separately from text chunks', () => {
    const out: any[] = [];
    const b = createFrameBatcher((f) => out.push(f), 40, () => {});
    b.push(chunk('a'));
    b.push({ type: 'thinking_chunk', session: 's', text: 'x', turn_id: 't1' } as any);
    b.push({ type: 'thinking_chunk', session: 's', text: 'y', turn_id: 't1' } as any);
    b.flush();
    expect(out).toHaveLength(2);
    expect(out[1].text).toBe('xy');
  });

  it('a stale timer from a flushed key does not prematurely flush the new pending buffer', () => {
    const out: any[] = [];
    const callbacks: Array<() => void> = [];
    const b = createFrameBatcher((f) => out.push(f), 40, (cb) => { callbacks.push(cb); });

    b.push(chunk('a', { block_index: 0 })); // key A — arms cb1
    b.push(chunk('b', { block_index: 1 })); // flushes A, arms cb2 for key B
    b.push(chunk('c', { block_index: 1 })); // merges into B, no new timer

    expect(out).toHaveLength(1);
    expect(out[0].text).toBe('a');
    expect(callbacks).toHaveLength(2);

    callbacks[0](); // stale cb1 for key A — must be a no-op now
    expect(out).toHaveLength(1);

    callbacks[1](); // cb2 for key B — flushes the coalesced B buffer
    expect(out).toHaveLength(2);
    expect(out[1].text).toBe('bc');
  });
});
