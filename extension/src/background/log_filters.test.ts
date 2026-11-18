import { describe, expect, it } from 'vitest';
import { filterConsoleEntries, filterNetworkEntries, normalizeSinceMs } from './log_filters';

describe('normalizeSinceMs', () => {
  it('treats values below 1e12 as unix seconds', () => {
    expect(normalizeSinceMs(1_700_000_000)).toBe(1_700_000_000_000);
  });
  it('keeps millisecond timestamps', () => {
    expect(normalizeSinceMs(1_700_000_000_123)).toBe(1_700_000_000_123);
  });
  it('returns null for empty input', () => {
    expect(normalizeSinceMs(undefined)).toBeNull();
    expect(normalizeSinceMs(0)).toBeNull();
  });
});

describe('filterConsoleEntries', () => {
  const entries = [
    { ts: 1_700_000_000_000, tab_id: 1, text: 'old tab1' },
    { ts: 1_700_000_010_000, tab_id: 2, text: 'new tab2' },
    { ts: 1_700_000_020_000, tab_id: 1, text: 'new tab1' },
  ];
  it('filters by tab_id', () => {
    const out = filterConsoleEntries(entries, { tabId: 1 });
    expect(out.map((e) => e.text)).toEqual(['old tab1', 'new tab1']);
  });
  it('filters by since_ts in seconds', () => {
    const out = filterConsoleEntries(entries, { sinceTs: 1_700_000_005 });
    expect(out.map((e) => e.text)).toEqual(['new tab2', 'new tab1']);
  });
  it('applies both filters', () => {
    const out = filterConsoleEntries(entries, { tabId: 1, sinceTs: 1_700_000_005 });
    expect(out.map((e) => e.text)).toEqual(['new tab1']);
  });
});

describe('filterNetworkEntries', () => {
  it('filters relative startMs using timeOrigin', () => {
    const origin = 1_700_000_000_000;
    const entries = [
      { name: 'a', startMs: 100, tab_id: 3 },
      { name: 'b', startMs: 5_000, tab_id: 3 },
    ];
    const out = filterNetworkEntries(entries, { sinceTs: 1_700_000_001, timeOriginMs: origin, tabId: 3 });
    expect(out.map((e) => e.name)).toEqual(['b']);
  });
});
