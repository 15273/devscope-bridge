import { describe, expect, it } from 'vitest';
import {
  appendTextDelta, appendThinkingDelta, markThinkingDone, segmentsText,
} from './turnSegments';

describe('turnSegments', () => {
  it('creates a text segment on first delta and appends on subsequent', () => {
    let s = appendTextDelta([], 0, 'hel');
    s = appendTextDelta(s, 0, 'lo');
    expect(s).toEqual([{ kind: 'text', blockIndex: 0, text: 'hello' }]);
  });

  it('a new block index opens a new text segment', () => {
    let s = appendTextDelta([], 0, 'before tool.');
    s = appendTextDelta(s, 2, 'after tool.');
    expect(s.map((x) => x.kind)).toEqual(['text', 'text']);
    expect((s[1] as any).blockIndex).toBe(2);
  });

  it('thinking accumulates into one segment with timing', () => {
    let s = appendThinkingDelta([], 'hm', 1000);
    s = appendThinkingDelta(s, 'mm', 1500);
    s = markThinkingDone(s, 2000);
    expect(s).toEqual([{ kind: 'thinking', text: 'hmmm', startedAt: 1000, doneAt: 2000 }]);
  });

  it('thinking then text keeps order and segmentsText ignores thinking', () => {
    let s = appendThinkingDelta([], 'plan', 1);
    s = appendTextDelta(s, 0, 'answer');
    expect(segmentsText(s)).toBe('answer');
    expect(s[0].kind).toBe('thinking');
  });

  it('text separated by a new block joins with a blank line in segmentsText', () => {
    let s = appendTextDelta([], 0, 'part one');
    s = appendTextDelta(s, 1, 'part two');
    expect(segmentsText(s)).toBe('part one\n\npart two');
  });

  it('opening a text segment closes a still-open trailing thinking segment', () => {
    let s = appendThinkingDelta([], 'plan', 1000);
    s = appendTextDelta(s, 0, 'answer', 1500);
    expect(s[0]).toEqual({ kind: 'thinking', text: 'plan', startedAt: 1000, doneAt: 1500 });
    expect(s[1]).toEqual({ kind: 'text', blockIndex: 0, text: 'answer' });
  });

  it('markThinkingDone closes every open thinking segment, not just the first', () => {
    let s = appendThinkingDelta([], 'first thought', 1000);
    s = appendTextDelta(s, 0, 'partial answer', 1500);
    s = appendThinkingDelta(s, 'second thought', 2000);
    s = markThinkingDone(s, 3000);
    const thinkingSegments = s.filter((seg) => seg.kind === 'thinking');
    expect(thinkingSegments).toEqual([
      { kind: 'thinking', text: 'first thought', startedAt: 1000, doneAt: 1500 },
      { kind: 'thinking', text: 'second thought', startedAt: 2000, doneAt: 3000 },
    ]);
  });
});
