import { describe, expect, it } from 'vitest';
import { tabsMatchingTitle } from '@/shared/tabBinding';
import type { BrowserTabSummary } from '@/shared/tabBinding';

function tab(partial: Partial<BrowserTabSummary> & { id: number; title: string }): BrowserTabSummary {
  return {
    url: 'https://hiremetech.com/en-il/v2/app/dashboard',
    active: false,
    windowId: 1,
    ...partial,
  };
}

describe('tabsMatchingTitle', () => {
  const tabs = [
    tab({ id: 1, title: 'לוח משרות הייטק | HireMe — 1.8M+ משרות', url: 'https://hiremetech.com/he-il/' }),
    tab({ id: 2, title: 'Personal Dashboard | HireMe', url: 'https://hiremetech.com/en-il/v2/app/dashboard' }),
    tab({ id: 3, title: 'Gmail' }),
  ];

  it('matches a quoted dashboard title', () => {
    const text = 'Orange banner should appear on "Personal Dashboard | HireMe" — click elements there';
    const hits = tabsMatchingTitle(text, tabs);
    expect(hits.map((t) => t.id)).toEqual([2]);
  });

  it('does not bind Gmail from an unrelated message', () => {
    expect(tabsMatchingTitle('hello there', tabs)).toEqual([]);
  });
});
