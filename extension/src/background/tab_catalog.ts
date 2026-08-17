/**
 * tab_catalog.ts — all Chrome windows + tabs for picker UI and browser_list_tabs.
 */
import type { BrowserTabSummary } from '@/shared/tabBinding';
import { isRestrictedUrl } from './tab_resolver';

export interface BrowserWindowSummary {
  id: number;
  focused: boolean;
  tabCount: number;
}

export interface TabCatalog {
  tabs: BrowserTabSummary[];
  windows: BrowserWindowSummary[];
}

export async function listTabCatalog(): Promise<TabCatalog> {
  const [rawTabs, rawWindows] = await Promise.all([
    chrome.tabs.query({}),
    chrome.windows.getAll({ windowTypes: ['normal'] }),
  ]);

  const focusedWindowId = rawWindows.find((w) => w.focused)?.id ?? null;
  const tabCountByWindow = new Map<number, number>();

  const tabs: BrowserTabSummary[] = [];
  for (const t of rawTabs) {
    if (t.id == null || isRestrictedUrl(t.url)) continue;
    tabCountByWindow.set(t.windowId, (tabCountByWindow.get(t.windowId) ?? 0) + 1);
    tabs.push({
      id: t.id,
      url: t.url ?? '',
      title: t.title ?? '',
      active: t.active ?? false,
      windowId: t.windowId,
      windowFocused: t.windowId === focusedWindowId,
    });
  }

  const windows: BrowserWindowSummary[] = rawWindows
    .filter((w) => w.id != null && (tabCountByWindow.get(w.id!) ?? 0) > 0)
    .map((w) => ({
      id: w.id!,
      focused: w.focused ?? false,
      tabCount: tabCountByWindow.get(w.id!) ?? 0,
    }))
    .sort((a, b) => Number(b.focused) - Number(a.focused));

  return { tabs, windows };
}
