/**
 * tab_resolver.ts — Resolve which tab a browser tool should operate on.
 *
 * Priority: explicit tabId → session bound tab → active tab in last-focused window.
 */

import { clearBoundTab, loadBoundTab, type BoundTab } from '@/shared/tabBinding';

export interface TabContext {
  id: number;
  url: string | undefined;
  windowId: number;
  title: string | undefined;
  active: boolean;
}

function isRestrictedUrl(url: string | undefined): boolean {
  if (!url) return true;
  const restricted = ['chrome://', 'chrome-extension://', 'edge://', 'about:', 'devtools://'];
  return restricted.some((p) => url.startsWith(p));
}

async function getActiveTab(): Promise<chrome.tabs.Tab | null> {
  try {
    const stored = await chrome.storage.session.get('panelHostWindowId');
    const hostWindowId = stored.panelHostWindowId as number | undefined;
    if (hostWindowId != null) {
      const [hostTab] = await chrome.tabs.query({ active: true, windowId: hostWindowId });
      if (hostTab?.id) return hostTab;
    }
  } catch {
    /* fall through */
  }
  const [focused] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  if (focused) return focused;
  const [current] = await chrome.tabs.query({ active: true, currentWindow: true });
  return current ?? null;
}

function toContext(raw: chrome.tabs.Tab): TabContext | null {
  if (!raw.id) return null;
  return {
    id: raw.id,
    url: raw.url,
    windowId: raw.windowId,
    title: raw.title,
    active: raw.active ?? false,
  };
}

async function getBoundTabRaw(sessionName: string): Promise<{ raw: chrome.tabs.Tab; bound: BoundTab } | null> {
  const bound = await loadBoundTab(sessionName);
  if (!bound) return null;
  try {
    const raw = await chrome.tabs.get(bound.tabId);
    if (isRestrictedUrl(raw.url)) {
      await clearBoundTab(sessionName);
      return null;
    }
    return { raw, bound };
  } catch {
    await clearBoundTab(sessionName);
    return null;
  }
}

/**
 * Resolve a tab by optional explicit id, optional session binding, or active tab.
 */
export async function resolveTab(
  tabId?: number,
  sessionName?: string,
): Promise<{ tab: TabContext; source: 'explicit' | 'bound' | 'active' } | { error: string }> {
  let raw: chrome.tabs.Tab | null = null;
  let source: 'explicit' | 'bound' | 'active' = 'active';

  if (tabId !== undefined) {
    try {
      raw = await chrome.tabs.get(tabId);
      source = 'explicit';
    } catch {
      return { error: `Tab ${tabId} not found or no longer open` };
    }
  } else if (sessionName) {
    const bound = await getBoundTabRaw(sessionName);
    if (bound) {
      raw = bound.raw;
      source = 'bound';
    }
  }

  if (!raw) {
    raw = await getActiveTab();
    source = 'active';
    if (!raw) {
      return { error: 'No active tab — bind a browser tab for this session or focus a page' };
    }
  }

  const tab = toContext(raw);
  if (!tab) {
    return { error: 'Tab has no id (internal Chrome tab — cannot script)' };
  }

  return { tab, source };
}

/**
 * For user-initiated pick/annotate: use the tab the user is looking at (focused
 * window's active tab), not a stale session-bound tab from an earlier message.
 */
export async function resolveTabForUserGesture(
  tabId?: number,
  sessionName?: string,
): Promise<
  { tab: TabContext; source: 'explicit' | 'focused' | 'bound' | 'active' }
  | { error: string }
> {
  if (tabId !== undefined) {
    return resolveTab(tabId, sessionName);
  }

  const [focused] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  if (focused?.id) {
    const tab = toContext(focused);
    if (tab && !isRestrictedUrl(tab.url)) {
      return { tab, source: 'focused' };
    }
  }

  return resolveTab(undefined, sessionName);
}

export { isRestrictedUrl };
