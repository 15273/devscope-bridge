/**
 * browser_tools_act.ts — Mutating/navigation tools: navigate, screenshot,
 * click, fill, scroll_to, select_option, hover, key_press,
 * wait_for_selector, wait_for_navigation.
 *
 * click, fill, scroll_to, select_option, hover scan all frames (AWS Console etc.).
 */

import type { BrowserToolResult } from './browser_tools_types';
import { resolveTab, isRestrictedUrl } from './tab_resolver';
import { runInFirstMatchingFrame, runInTabWithArgs } from './frame_runner';
import { unwrapInjectedError } from './browser_tools_read';
import { injectedDomAction } from './dom_interact_inject';
import { compressFullPageCapture } from './elementScreenshot';
import { resolveRef } from './ref_map';
import { cdpClickSelector, cdpFillSelector, cdpScreenshot } from './cdp_driver';
import { resolveBrowseRoute } from './browse_router';
import { notifyAgentAction } from './agent_action_feedback';

// ─── Navigation throttle ──────────────────────────────────────────────────────

const NAV_WINDOW_MS = 20_000;
const NAV_MAX = 5;
const _navTimes: number[] = [];

export async function browserNavigate(url: string, tabId?: number): Promise<BrowserToolResult> {
  const resolved = await resolveTab(tabId);
  if ('error' in resolved) return { ok: false, error: resolved.error };
  const { tab } = resolved;
  if (!url) return { ok: false, error: 'url is required' };
  if (tab.url === url || tab.url === `${url}/` || `${tab.url}/` === url) {
    return { ok: true, data: { tabId: tab.id, url: tab.url, title: tab.title, note: 'Already on this URL — not reloaded' } };
  }
  const now = Date.now();
  while (_navTimes.length && now - _navTimes[0] > NAV_WINDOW_MS) _navTimes.shift();
  if (_navTimes.length >= NAV_MAX) {
    return { ok: false, error: `Navigation throttled: ${NAV_MAX}+ page loads within ${NAV_WINDOW_MS / 1000}s. Stop reloading — change your approach.` };
  }
  _navTimes.push(now);
  const updated = await chrome.tabs.update(tab.id, { url });
  return { ok: true, data: { tabId: updated.id, url: updated.url, title: updated.title } };
}

const CAPTURE_SETTLE_MS = 180;
const SCREENSHOT_TIMEOUT_MS = 20_000;

/** Chrome only captures the active tab in a focused window — focus first. */
async function focusTabForCapture(tab: { id: number; windowId: number }): Promise<void> {
  await chrome.windows.update(tab.windowId, { focused: true });
  await chrome.tabs.update(tab.id, { active: true });
  await new Promise((r) => setTimeout(r, CAPTURE_SETTLE_MS));
}

async function getActiveTabIdInWindow(windowId: number): Promise<number | undefined> {
  const [active] = await chrome.tabs.query({ windowId, active: true });
  return active?.id;
}

/** Restore whichever tab the user had active before a brief agent focus for capture. */
async function restorePreviousActiveTab(windowId: number, previousActiveId: number | undefined, agentTabId: number): Promise<void> {
  if (!previousActiveId || previousActiveId === agentTabId) return;
  try {
    await chrome.tabs.update(previousActiveId, { active: true });
  } catch {
    /* tab closed — nothing to restore */
  }
}

async function captureTabScreenshot(tab: { id: number; windowId: number; url?: string; title?: string }, fullPage: boolean): Promise<BrowserToolResult> {
  const previousActiveId = await getActiveTabIdInWindow(tab.windowId);
  const needsFocus = previousActiveId !== tab.id;

  const captureOnce = async (): Promise<string> =>
    chrome.tabs.captureVisibleTab(tab.windowId, { format: 'jpeg', quality: 72 });

  try {
    let raw: string;
    try {
      if (needsFocus) await focusTabForCapture(tab);
      raw = await captureOnce();
    } catch (firstErr) {
      if (!needsFocus) {
        await focusTabForCapture(tab);
        raw = await captureOnce();
      } else {
        throw firstErr;
      }
    }
    const dataUrl = await compressFullPageCapture(raw);
    return {
      ok: true,
      data: {
        dataUrl,
        fullPage,
        note: fullPage ? 'Only visible viewport captured (full_page ignored in v1)' : undefined,
        tabId: tab.id,
        url: tab.url,
        title: tab.title,
        focusRestored: needsFocus && previousActiveId !== tab.id,
      },
    };
  } finally {
    if (needsFocus) {
      await restorePreviousActiveTab(tab.windowId, previousActiveId, tab.id);
    }
  }
}

export async function browserScreenshot(fullPage: boolean, tabId?: number): Promise<BrowserToolResult> {
  const resolved = await resolveTab(tabId);
  if ('error' in resolved) return { ok: false, error: resolved.error };
  const route = await resolveBrowseRoute('browser_screenshot');
  if (fullPage && route.driver === 'cdp' && resolved.tab.id) {
    const cdp = await cdpScreenshot(resolved.tab.id, true);
    if (cdp.ok) {
      return {
        ...cdp,
        data: {
          ...(cdp.data as Record<string, unknown>),
          tabId: resolved.tab.id,
          url: resolved.tab.url,
          title: resolved.tab.title,
        },
      };
    }
  }
  const { tab } = resolved;

  let timeoutId: ReturnType<typeof setTimeout> | undefined;
  try {
    const result = await Promise.race([
      captureTabScreenshot(tab, fullPage),
      new Promise<BrowserToolResult>((_, reject) => {
        timeoutId = setTimeout(
          () => reject(new Error(`Screenshot timed out after ${SCREENSHOT_TIMEOUT_MS / 1000}s`)),
          SCREENSHOT_TIMEOUT_MS,
        );
      }),
    ]);
    return result;
  } catch (err) {
    const msg = String(err);
    if (/cannot capture|not in focus|activeTab|permission/i.test(msg)) {
      return {
        ok: false,
        error:
          `${msg} — Chrome requires the tab's window to be focused for screenshots. ` +
          'Click the page tab once, then retry.',
      };
    }
    return { ok: false, error: msg };
  } finally {
    if (timeoutId !== undefined) clearTimeout(timeoutId);
  }
}

export async function browserClick(
  selector: string,
  tabId?: number,
  ref?: number,
): Promise<BrowserToolResult> {
  const resolved = await resolveTab(tabId);
  if ('error' in resolved) return { ok: false, error: resolved.error };
  let sel = selector;
  if (ref != null && resolved.tab.id) {
    const loc = resolveRef(resolved.tab.id, ref);
    if (!loc) return { ok: false, error: `Ref @${ref} not found — run browser_snapshot first` };
    sel = loc.selector;
  }
  if (!sel) return { ok: false, error: 'selector or ref is required' };

  const route = await resolveBrowseRoute('browser_click');
  if (route.driver === 'cdp' && resolved.tab.id) {
    const cdp = await cdpClickSelector(resolved.tab.id, sel);
    if (cdp.ok) {
      void notifyAgentAction(resolved.tab.id, sel);
      return cdp;
    }
  }

  const result = await runInFirstMatchingFrame(
    injectedDomAction,
    ['click', sel],
    'ISOLATED',
    tabId,
  ).then(unwrapInjectedError);
  if (result.ok && resolved.tab.id) void notifyAgentAction(resolved.tab.id, sel);
  return result;
}

export async function browserFill(
  selector: string,
  value: string,
  tabId?: number,
  ref?: number,
): Promise<BrowserToolResult> {
  const resolved = await resolveTab(tabId);
  if ('error' in resolved) return { ok: false, error: resolved.error };
  let sel = selector;
  if (ref != null && resolved.tab.id) {
    const loc = resolveRef(resolved.tab.id, ref);
    if (!loc) return { ok: false, error: `Ref @${ref} not found — run browser_snapshot first` };
    sel = loc.selector;
  }
  if (!sel) return { ok: false, error: 'selector or ref is required' };

  const route = await resolveBrowseRoute('browser_fill');
  if (route.driver === 'cdp' && resolved.tab.id) {
    const cdp = await cdpFillSelector(resolved.tab.id, sel, value);
    if (cdp.ok) {
      void notifyAgentAction(resolved.tab.id, sel);
      return cdp;
    }
  }

  const result = await runInFirstMatchingFrame(
    (sel: string, val: string) => {
      const el = document.querySelector(sel) as HTMLInputElement | HTMLTextAreaElement | null;
      if (!el) return { error: `Element not found: ${sel}` };
      el.focus(); el.value = val;
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
      return { success: true, selector: sel, value: val, frameUrl: location.href };
    },
    [sel, value], 'ISOLATED', tabId,
  ).then(unwrapInjectedError);
  if (result.ok && resolved.tab.id) void notifyAgentAction(resolved.tab.id, sel);
  return result;
}

export async function browserScrollTo(selector: string, tabId?: number): Promise<BrowserToolResult> {
  if (!selector) return { ok: false, error: 'selector is required' };
  return runInTabWithArgs(
    (sel: string) => {
      const el = document.querySelector(sel);
      if (!el) return { error: `Element not found: ${sel}` };
      el.scrollIntoView({ behavior: 'instant', block: 'center', inline: 'center' });
      return { ok: true, selector: sel };
    },
    [selector], 'ISOLATED', tabId,
  ).then(unwrapInjectedError);
}

export async function browserSelectOption(selector: string, value: string, tabId?: number): Promise<BrowserToolResult> {
  if (!selector) return { ok: false, error: 'selector is required' };
  return runInFirstMatchingFrame(
    injectedDomAction,
    ['select_option', selector, value],
    'ISOLATED',
    tabId,
  ).then(unwrapInjectedError);
}

export async function browserHover(selector: string, tabId?: number): Promise<BrowserToolResult> {
  if (!selector) return { ok: false, error: 'selector is required' };
  return runInFirstMatchingFrame(
    injectedDomAction,
    ['hover', selector],
    'ISOLATED',
    tabId,
  ).then(unwrapInjectedError);
}

export async function browserKeyPress(key: string, selector?: string, tabId?: number): Promise<BrowserToolResult> {
  if (!key) return { ok: false, error: 'key is required' };
  return runInTabWithArgs(
    (k: string, sel: string | null) => {
      const target: Element | null = sel ? document.querySelector(sel) : document.activeElement;
      if (sel && !target) return { error: `Element not found: ${sel}` };
      const el = (target ?? document.body) as HTMLElement;
      const opts: KeyboardEventInit = { key: k, bubbles: true, cancelable: true };
      el.dispatchEvent(new KeyboardEvent('keydown', opts));
      if (k === 'Enter' && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA')) el.dispatchEvent(new KeyboardEvent('keypress', opts));
      el.dispatchEvent(new KeyboardEvent('keyup', opts));
      return { ok: true, key: k, selector: sel ?? '(active element)' };
    },
    [key, selector ?? null], 'ISOLATED', tabId,
  ).then(unwrapInjectedError);
}

export async function browserWaitForSelector(selector: string, timeoutMs: number, tabId?: number): Promise<BrowserToolResult> {
  if (!selector) return { ok: false, error: 'selector is required' };
  return runInTabWithArgs(
    (sel: string, timeout: number) =>
      new Promise<Record<string, unknown>>((resolve) => {
        const start = Date.now();
        const tick = (): void => {
          let found = false;
          try { found = document.querySelector(sel) !== null; } catch {
            resolve({ found: false, waitedMs: Date.now() - start, error: `Invalid selector: ${sel}` }); return;
          }
          if (found) { resolve({ found: true, waitedMs: Date.now() - start }); return; }
          if (Date.now() - start >= timeout) { resolve({ found: false, waitedMs: Date.now() - start }); return; }
          setTimeout(tick, 100);
        };
        tick();
      }),
    [selector, timeoutMs], 'ISOLATED', tabId,
  ).then(unwrapInjectedError);
}

export async function browserWaitForNavigation(timeoutMs: number, tabId?: number): Promise<BrowserToolResult> {
  const resolved = await resolveTab(tabId);
  if ('error' in resolved) return { ok: false, error: resolved.error };
  const targetTabId = resolved.tab.id;
  const deadline = Date.now() + timeoutMs;
  const pollComplete = async (): Promise<chrome.tabs.Tab | null> => {
    while (Date.now() < deadline) {
      const current = await chrome.tabs.get(targetTabId).catch(() => null);
      if (!current) return null;
      if (current.status === 'complete') return current;
      await new Promise((r) => setTimeout(r, 100));
    }
    return chrome.tabs.get(targetTabId).catch(() => null);
  };
  const finalTab = await pollComplete();
  if (!finalTab) return { ok: false, error: 'Tab is no longer available' };
  if (!isRestrictedUrl(finalTab.url)) {
    const remaining = Math.max(0, deadline - Date.now());
    await runInTabWithArgs(
      (timeout: number) => new Promise<boolean>((resolve) => {
        if (document.readyState === 'complete') { resolve(true); return; }
        const onLoad = (): void => resolve(true);
        window.addEventListener('load', onLoad, { once: true });
        setTimeout(() => resolve(document.readyState === 'complete'), timeout);
      }),
      [remaining], 'ISOLATED', tabId,
    );
  }
  return { ok: true, data: { url: finalTab.url ?? '', complete: finalTab.status === 'complete', tabId: targetTabId } };
}

/** Open a new tab in an existing Chrome window (defaults to focused window). */
export async function browserNewPage(
  url: string,
  windowId?: number,
  active = false,
): Promise<BrowserToolResult> {
  let targetWindowId = windowId;
  if (targetWindowId == null) {
    const wins = await chrome.windows.getAll({ windowTypes: ['normal'] });
    const focused = wins.find((w) => w.focused);
    targetWindowId = (focused ?? wins[0])?.id;
  }
  if (targetWindowId == null) {
    return { ok: false, error: 'No Chrome window found to open a new tab in.' };
  }
  try {
    const tab = await chrome.tabs.create({
      url: url || 'about:blank',
      windowId: targetWindowId,
      active,
    });
    return {
      ok: true,
      data: {
        tabId: tab.id,
        windowId: tab.windowId,
        url: tab.pendingUrl ?? tab.url ?? url,
        active,
        note: active
          ? 'New tab opened in foreground. Prefer active=false so the user can keep working in their current tab.'
          : 'New tab opened in background — bind this tab_id for automation without stealing user focus.',
      },
    };
  } catch (err) {
    return { ok: false, error: `Could not open new tab: ${String(err)}` };
  }
}

/**
 * Inject a file into a file input via MAIN-world DataTransfer.
 *
 * The bridge pre-encodes the file as base64. This function runs a self-contained
 * injected function in the MAIN world (required so DataTransfer.files assignment
 * reaches the page's own File/DataTransfer classes, not the extension's isolated copy).
 * It scans all frames (allFrames:true) so Workday iframes are covered.
 */
export async function browserUploadFile(
  selector: string,
  base64: string,
  filename: string,
  mime: string,
  tabId?: number,
): Promise<BrowserToolResult> {
  if (!selector) return { ok: false, error: 'selector is required' };

  const resolved = await resolveTab(tabId);
  if ('error' in resolved) return { ok: false, error: resolved.error };
  const { tab } = resolved;
  if (isRestrictedUrl(tab.url)) {
    return { ok: false, error: `Cannot script restricted page: ${tab.url ?? '(unknown)'}` };
  }

  // Self-contained MAIN-world function — no closure refs, no imports.
  function setFileInputInPage(
    sel: string,
    b64: string,
    fname: string,
    fmime: string,
  ): { ok: boolean; filename?: string; size?: number; error?: string } {
    const input = document.querySelector(sel) as HTMLInputElement | null;
    if (!input) return { ok: false, error: 'input not found: ' + sel };
    const bin = atob(b64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    const file = new File([bytes], fname, { type: fmime });
    const dt = new DataTransfer();
    dt.items.add(file);
    input.files = dt.files;
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
    return { ok: true, filename: fname, size: bytes.length };
  }

  try {
    const rawResults = await chrome.scripting.executeScript({
      target: { tabId: tab.id, allFrames: true },
      world: 'MAIN',
      func: setFileInputInPage,
      args: [selector, base64, filename, mime],
    });

    // Find the first frame where ok:true
    for (const r of rawResults) {
      const res = r.result as { ok: boolean; filename?: string; size?: number; error?: string } | null;
      if (res?.ok) {
        return {
          ok: true,
          data: { filename: res.filename, size: res.size, frameId: r.frameId, tabId: tab.id },
        };
      }
    }

    // All frames returned not-ok — report the first error
    const firstError = rawResults
      .map((r) => (r.result as { error?: string } | null)?.error)
      .find(Boolean);
    return { ok: false, error: firstError ?? 'input not found in any frame' };
  } catch (err) {
    return { ok: false, error: String(err) };
  }
}

/** Focus the Chrome window and tab (works across windows; does not require last-focused window). */
export async function browserFocusTab(tabId?: number): Promise<BrowserToolResult> {
  const resolved = await resolveTab(tabId);
  if ('error' in resolved) return { ok: false, error: resolved.error };
  const { tab } = resolved;
  try {
    await chrome.windows.update(tab.windowId, { focused: true });
    await chrome.tabs.update(tab.id, { active: true });
  } catch (err) {
    return { ok: false, error: `Could not focus tab ${tab.id}: ${String(err)}` };
  }
  const updated = await chrome.tabs.get(tab.id);
  return {
    ok: true,
    data: {
      tabId: updated.id,
      windowId: updated.windowId,
      url: updated.url,
      title: updated.title,
      note: 'Window and tab focused — user can see this page.',
    },
  };
}
