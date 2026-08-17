/**
 * browseBackend.ts — how browser tools reach the page (same tab, different drivers).
 */
export type BrowseBackend = 'extension' | 'cdp' | 'auto';

export interface BrowseBackendInfo {
  id: BrowseBackend;
  label: string;
  summary: string;
}

/** Same browser the user sees — never a separate Playwright launch. */
export const BROWSE_BACKENDS: BrowseBackendInfo[] = [
  {
    id: 'extension',
    label: 'This tab',
    summary: 'Inject scripts into your current tab. Fast, no DevTools banner.',
  },
  {
    id: 'cdp',
    label: 'CDP',
    summary: 'Chrome DevTools Protocol on the same tab — stronger clicks & dropdowns.',
  },
  {
    id: 'auto',
    label: 'Auto',
    summary: 'Extension for reads; CDP for tricky clicks/fills when available.',
  },
];

export function browseBackendInfo(id: BrowseBackend): BrowseBackendInfo {
  return BROWSE_BACKENDS.find((b) => b.id === id) ?? BROWSE_BACKENDS[0];
}

/** Tools that benefit from CDP when auto/cdp is selected (phase 2+). */
export const CDP_PREFERRED_TOOLS = new Set([
  'browser_click',
  'browser_fill',
  'browser_select_option',
  'browser_hover',
  'browser_screenshot', // full_page path
]);
