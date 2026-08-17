/**
 * recording_halo.ts — manage the cursor-halo overlay on the tab being recorded.
 *
 * Injected at recording start, re-injected after in-tab navigations (the
 * overlay dies with the old document), removed at recording stop.
 */

import {
  recordingHaloCleanupInjected,
  recordingHaloInjected,
} from './recording_halo_inject';

let activeHaloTabId: number | undefined;
let navigationHookInstalled = false;

function injectHalo(tabId: number): void {
  chrome.scripting
    .executeScript({ target: { tabId }, func: recordingHaloInjected })
    .catch(() => {});
}

function ensureNavigationRelink(): void {
  if (navigationHookInstalled) return;
  navigationHookInstalled = true;

  chrome.webNavigation.onCommitted.addListener((details) => {
    if (details.frameId !== 0) return;
    if (activeHaloTabId !== details.tabId) return;
    injectHalo(details.tabId);
  });

  chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
    if (activeHaloTabId !== tabId) return;
    if (changeInfo.status !== 'complete') return;
    injectHalo(tabId);
  });
}

export function startRecordingHalo(tabId: number): void {
  if (activeHaloTabId != null && activeHaloTabId !== tabId) {
    stopRecordingHalo();
  }
  activeHaloTabId = tabId;
  ensureNavigationRelink();
  injectHalo(tabId);
}

export function stopRecordingHalo(): void {
  const tabId = activeHaloTabId;
  activeHaloTabId = undefined;
  if (tabId == null) return;
  chrome.scripting
    .executeScript({ target: { tabId }, func: recordingHaloCleanupInjected })
    .catch(() => {});
}
