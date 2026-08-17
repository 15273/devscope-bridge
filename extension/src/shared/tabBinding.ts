/**
 * tabBinding.ts — per-session browser tab target (which tab/window DevScope controls).
 */

import { safeLocalSet } from './storageWrite';

export interface BoundTab {
  tabId: number;
  url: string;
  title: string;
  windowId: number;
  boundAt: string;
}

export interface BrowserTabSummary {
  id: number;
  url: string;
  title: string;
  active: boolean;
  windowId: number;
  /** True when this tab's window is the last-focused Chrome window. */
  windowFocused?: boolean;
}

const KEY_PREFIX = 'session.boundTab.';

function storageKey(sessionName: string): string {
  return KEY_PREFIX + sessionName;
}

export async function loadBoundTab(sessionName: string): Promise<BoundTab | null> {
  const result = await chrome.storage.local.get(storageKey(sessionName));
  const v = result[storageKey(sessionName)] as BoundTab | undefined;
  if (!v || typeof v.tabId !== 'number') return null;
  return v;
}

export async function saveBoundTab(sessionName: string, tab: BoundTab): Promise<void> {
  try {
    await safeLocalSet({ [storageKey(sessionName)]: tab }, { keepSession: sessionName });
  } catch (err) {
    // Binding still works in-memory; cache write must not abort send.
    console.warn('[DevScope] saveBoundTab failed:', err);
  }
}

export async function clearBoundTab(sessionName: string): Promise<void> {
  await chrome.storage.local.remove(storageKey(sessionName));
}

export function tabToBound(tab: chrome.tabs.Tab): BoundTab | null {
  if (tab.id == null) return null;
  return {
    tabId: tab.id,
    url: tab.url ?? '',
    title: tab.title ?? '',
    windowId: tab.windowId,
    boundAt: new Date().toISOString(),
  };
}

const URL_RE = /https?:\/\/[^\s<>"')\]]+/gi;

/** Extract http(s) URLs from user/agent text for auto tab matching. */
export function extractUrls(text: string): string[] {
  const found = text.match(URL_RE) ?? [];
  return [...new Set(found.map((u) => u.replace(/[.,;:!?)]+$/, '')))];
}

export function hostnameMatches(tabUrl: string, hintUrl: string): boolean {
  try {
    return new URL(tabUrl).hostname === new URL(hintUrl).hostname;
  } catch {
    return false;
  }
}

export function shortTabLabel(title: string, url: string, max = 36): string {
  const base = title.trim() || url;
  if (base.length <= max) return base;
  return `${base.slice(0, max - 1)}…`;
}
