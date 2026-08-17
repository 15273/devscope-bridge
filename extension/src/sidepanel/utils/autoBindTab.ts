/**
 * autoBindTab.ts — match user message URLs to open tabs and bind the session target.
 */
import type { BrowserTabSummary, BoundTab } from '@/shared/tabBinding';
import {
  extractUrls,
  hostnameMatches,
  loadBoundTab,
  saveBoundTab,
  tabToBound,
} from '@/shared/tabBinding';

export type AutoBindResult =
  | { status: 'bound'; tab: BoundTab }
  | { status: 'ambiguous'; candidates: BrowserTabSummary[]; hintUrl: string }
  | { status: 'none' };

export async function listTabsViaBackground(): Promise<BrowserTabSummary[]> {
  const res = (await chrome.runtime.sendMessage({ kind: 'list_browser_tabs' })) as {
    ok?: boolean;
    tabs?: BrowserTabSummary[];
  };
  return res?.tabs ?? [];
}

export async function autoBindTabFromText(
  sessionName: string,
  text: string,
): Promise<AutoBindResult> {
  const urls = extractUrls(text);
  if (urls.length === 0) return { status: 'none' };

  const tabs = await listTabsViaBackground();
  for (const hintUrl of urls) {
    const matches = tabs.filter((t) => hostnameMatches(t.url, hintUrl));
    if (matches.length === 1) {
      const bound: BoundTab = {
        tabId: matches[0].id,
        url: matches[0].url,
        title: matches[0].title,
        windowId: matches[0].windowId,
        boundAt: new Date().toISOString(),
      };
      await saveBoundTab(sessionName, bound);
      return { status: 'bound', tab: bound };
    }
    if (matches.length > 1) {
      return { status: 'ambiguous', candidates: matches, hintUrl };
    }
  }
  return { status: 'none' };
}

export async function bindTabById(sessionName: string, tabId: number): Promise<BoundTab | null> {
  try {
    const tab = await chrome.tabs.get(tabId);
    const bound = tabToBound(tab);
    if (!bound) return null;
    await saveBoundTab(sessionName, bound);
    return bound;
  } catch {
    return null;
  }
}

/**
 * Bind the active tab in the browser window that hosts this side panel.
 * Avoids lastFocusedWindow — when the panel is focused that often resolves wrong.
 */
export async function bindHostWindowActiveTab(sessionName: string): Promise<BoundTab | null> {
  let windowId: number | undefined;
  try {
    const win = await chrome.windows.getCurrent();
    windowId = win.id;
  } catch {
    /* fall back below */
  }
  const query: chrome.tabs.QueryInfo =
    windowId != null
      ? { active: true, windowId }
      : { active: true, lastFocusedWindow: true };
  const [tab] = await chrome.tabs.query(query);
  if (!tab) return null;
  const bound = tabToBound(tab);
  if (!bound) return null;
  await saveBoundTab(sessionName, bound);
  return bound;
}

/** @deprecated Prefer bindHostWindowActiveTab — kept for call sites. */
export async function bindFocusedTab(sessionName: string): Promise<BoundTab | null> {
  return bindHostWindowActiveTab(sessionName);
}

/** Auto-bind when the session has no valid bound tab and the user allows it. */
/** Focus the bound tab's window and make it active. */
export async function focusBoundTab(tab: BoundTab): Promise<boolean> {
  try {
    await chrome.windows.update(tab.windowId, { focused: true });
    await chrome.tabs.update(tab.tabId, { active: true });
    return true;
  } catch {
    return false;
  }
}

export async function tryAutoBindIfEmpty(
  sessionName: string,
  autoBind: boolean,
): Promise<BoundTab | null> {
  if (!autoBind) return null;
  const existing = await loadBoundTab(sessionName);
  if (existing) {
    try {
      await chrome.tabs.get(existing.tabId);
      return existing;
    } catch {
      /* stale binding — rebind below */
    }
  }
  return bindHostWindowActiveTab(sessionName);
}
