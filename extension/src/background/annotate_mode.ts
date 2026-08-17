/**
 * annotate_mode.ts — start/stop multi-element annotate session on the active tab.
 */

import type { BrowserToolResult } from './browser_tools_types';
import { resolveTabForUserGesture, isRestrictedUrl } from './tab_resolver';
import { captureElementSnippet } from './elementScreenshot';
import { saveBoundTab, tabToBound } from '@/shared/tabBinding';
import {
  annotateModeCleanupInjected,
  annotateModeInjected,
} from './annotate_mode_inject';

let activeAnnotateTabId: number | undefined;
let navigationHookInstalled = false;

function cleanupAllFrames(tabId: number): void {
  chrome.scripting
    .executeScript({
      target: { tabId, allFrames: true },
      func: annotateModeCleanupInjected,
    })
    .catch(() => {});
}

function injectAnnotate(tabId: number): Promise<boolean> {
  return chrome.scripting
    .executeScript({
      target: { tabId, allFrames: true },
      func: annotateModeInjected,
    })
    .then((results) =>
      results.some(
        (r) =>
          r?.result &&
          typeof r.result === 'object' &&
          (r.result as { started?: boolean }).started === true &&
          (r.result as { isTop?: boolean }).isTop === true,
      ),
    )
    .catch(() => false);
}

function ensureNavigationRelink(): void {
  if (navigationHookInstalled) return;
  navigationHookInstalled = true;

  chrome.webNavigation.onCommitted.addListener((details) => {
    if (details.frameId !== 0) return;
    if (activeAnnotateTabId !== details.tabId) return;
    void injectAnnotate(details.tabId);
  });

  chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
    if (activeAnnotateTabId !== tabId) return;
    if (changeInfo.status !== 'complete') return;
    void injectAnnotate(tabId);
  });
}

export async function stopAnnotateMode(tabId?: number): Promise<BrowserToolResult> {
  const id = tabId ?? activeAnnotateTabId;
  if (id == null) return { ok: true, data: { stopped: false } };
  cleanupAllFrames(id);
  if (activeAnnotateTabId === id) activeAnnotateTabId = undefined;
  return { ok: true, data: { stopped: true } };
}

export async function startAnnotateMode(
  tabId?: number,
  sessionName?: string,
): Promise<BrowserToolResult> {
  const resolved = await resolveTabForUserGesture(tabId, sessionName);
  if ('error' in resolved) return { ok: false, error: resolved.error };
  const { tab } = resolved;
  if (isRestrictedUrl(tab.url)) {
    return {
      ok: false,
      error: `Cannot script restricted page: ${tab.url ?? '(unknown)'}`,
    };
  }

  if (activeAnnotateTabId != null && activeAnnotateTabId !== tab.id) {
    await stopAnnotateMode(activeAnnotateTabId);
  }

  // Tear down any stale inject on this tab (HMR reload, partial cleanup, etc.)
  cleanupAllFrames(tab.id);

  try {
    await chrome.tabs.update(tab.id, { active: true });
  } catch {
    /* optional — picking still works if tab is already visible */
  }

  const started = await injectAnnotate(tab.id);
  if (!started) {
    return {
      ok: false,
      error:
        'Could not start pick mode on this page — click the page tab once, then try again.',
    };
  }

  activeAnnotateTabId = tab.id;
  ensureNavigationRelink();

  if (sessionName) {
    try {
      const raw = await chrome.tabs.get(tab.id);
      const bound = tabToBound(raw);
      if (bound) await saveBoundTab(sessionName, bound);
    } catch {
      /* binding optional */
    }
  }

  return {
    ok: true,
    data: {
      started: true,
      tabId: tab.id,
      tabTitle: tab.title,
      tabUrl: tab.url,
    },
  };
}

/** Enrich staged element with screenshot and broadcast to side panel. */
export async function handleAnnotationAttached(
  element: Record<string, unknown>,
  senderTabId?: number,
): Promise<void> {
  const tabId = senderTabId ?? activeAnnotateTabId;
  if (tabId != null && element.boundingBox && typeof element.boundingBox === 'object') {
    try {
      const tab = await chrome.tabs.get(tabId);
      const box = element.boundingBox as { x: number; y: number; width: number; height: number };
      const snippet = await captureElementSnippet(tabId, tab.windowId, box);
      if (snippet) element.screenshotSnippet = snippet;
    } catch {
      /* screenshot optional */
    }
  }
  chrome.runtime.sendMessage({ kind: 'annotation_staged', element }).catch(() => {});
}
