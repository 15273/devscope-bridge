/**
 * messageContext.ts — merge session bound-tab metadata into outbound user context.
 */
import type { BoundTab } from './tabBinding';
import { clearBoundTab, loadBoundTab, saveBoundTab, tabToBound } from './tabBinding';
import type { MessageContext } from './frames';

export interface BoundTabContext {
  tabId: number;
  url: string;
  title: string;
  windowId: number;
}

function toBoundTabContext(tab: BoundTab): BoundTabContext {
  return {
    tabId: tab.tabId,
    url: tab.url,
    title: tab.title,
    windowId: tab.windowId,
  };
}

/** Refresh bound tab from Chrome, persist updates, return context field or null. */
export async function refreshBoundTab(sessionName: string): Promise<BoundTab | null> {
  const stored = await loadBoundTab(sessionName);
  if (!stored) return null;
  try {
    const raw = await chrome.tabs.get(stored.tabId);
    if (!raw.url || /^(chrome|chrome-extension|devtools|edge):/i.test(raw.url)) {
      await clearBoundTab(sessionName);
      return null;
    }
    const fresh = tabToBound(raw);
    if (!fresh) {
      await clearBoundTab(sessionName);
      return null;
    }
    if (
      fresh.url !== stored.url ||
      fresh.title !== stored.title ||
      fresh.windowId !== stored.windowId
    ) {
      await saveBoundTab(sessionName, fresh);
    }
    return fresh;
  } catch {
    // Dead tab id — never inject it into PAGE CONTEXT or Grok will aim at a ghost.
    await clearBoundTab(sessionName);
    return null;
  }
}

/** Attach live bound-tab metadata so the agent knows which tab to control. */
export async function enrichContextWithBoundTab(
  sessionName: string,
  context?: MessageContext,
): Promise<MessageContext | undefined> {
  let bound = await refreshBoundTab(sessionName);
  if (!bound) {
    try {
      const [focused] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
      const live = focused ? tabToBound(focused) : null;
      if (live && live.url && !/^(chrome|chrome-extension|devtools):/i.test(live.url)) {
        await saveBoundTab(sessionName, live);
        bound = live;
      }
    } catch {
      /* keep unbound */
    }
  }
  const elements = context?.elements ?? [];
  const attachments = context?.attachments ?? [];
  if (!bound && elements.length === 0 && attachments.length === 0) {
    return undefined;
  }
  return {
    elements,
    attachments,
    ...(bound ? { boundTab: toBoundTabContext(bound) } : {}),
  };
}
