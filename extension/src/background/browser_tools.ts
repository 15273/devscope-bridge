/**
 * browser_tools.ts — Dispatch MCP browser-control tool calls.
 */
import { resolveBrowseRoute } from './browse_router';
import { resolveTab } from './tab_resolver';
import { clearBoundTab, loadBoundTab } from '@/shared/tabBinding';

export type { BrowserToolResult } from './browser_tools_types';
export { pickElement } from './pick_element';

import type { BrowserToolResult } from './browser_tools_types';

import {
  browserGetPageInfo,
  browserSnapshot,
  browserGetElements,
  browserAssertText,
  browserEvaluate,
  browserGetNetwork,
  browserGetConsole,
  browserHighlight,
} from './browser_tools_read';

import {
  browserNavigate,
  browserScreenshot,
  browserClick,
  browserFill,
  browserScrollTo,
  browserSelectOption,
  browserHover,
  browserKeyPress,
  browserWaitForSelector,
  browserWaitForNavigation,
  browserFocusTab,
  browserNewPage,
  browserUploadFile,
} from './browser_tools_act';

import { listTabCatalog } from './tab_catalog';
// Static import (NOT dynamic): in the MV3 service worker a dynamic import()
// is wrapped by Vite's __vitePreload helper, which touches `document` and
// throws "window is not defined" in the worker scope. Bundling runWaStore
// into the SW chunk avoids that entirely.
import { runWaStore } from './wa_store_runner';

async function sendLinkedInTabMessage(
  tabId: number | undefined,
  message: Record<string, unknown>,
): Promise<BrowserToolResult> {
  if (tabId === undefined) {
    return { ok: false, error: 'linkedin tool requires a tab_id or bound tab on linkedin.com' };
  }
  try {
    const response = await chrome.tabs.sendMessage(tabId, message);
    return { ok: true, data: response as Record<string, unknown> };
  } catch (err) {
    return {
      ok: false,
      error: String(err instanceof Error ? err.message : err),
      data: { hint: 'Ensure DevScope LinkedIn content scripts are loaded (rebuild dist, reload extension).' },
    };
  }
}

async function browserListTabs(sessionName?: string): Promise<BrowserToolResult> {
  const { tabs, windows } = await listTabCatalog();
  const bound = sessionName ? await loadBoundTab(sessionName) : null;
  const tabsWithBound = tabs.map((t) => ({
    ...t,
    is_bound: bound?.tabId === t.id,
  }));
  return {
    ok: true,
    data: {
      windows,
      total_windows: windows.length,
      total_tabs: tabsWithBound.length,
      tabs: tabsWithBound,
      bound_tab_id: bound?.tabId ?? null,
      bound_tab_title: bound?.title ?? null,
      bound_tab_url: bound?.url ?? null,
      bound_window_id: bound?.windowId ?? null,
      note: bound
        ? `Session bound to tab ${bound.tabId} in window ${bound.windowId} (${bound.title}). OMIT tab_id on browser tools — works across all Chrome windows.`
        : 'Lists ALL Chrome windows and tabs. Bind a tab in DevScope panel, or pass tab_id from this list. Stale tab_ids fail — always use ids from this response.',
    },
  };
}

interface ResolvedTabTarget {
  tabId: number;
  source: 'bound' | 'explicit' | 'active';
  ignoredTabId?: number;
}

async function resolveEffectiveTabId(
  explicitTabId: number | undefined,
  sessionName: string | undefined,
  tool: string,
): Promise<ResolvedTabTarget | BrowserToolResult> {
  if (tool === 'browser_list_tabs') {
    return { tabId: -1, source: 'active' };
  }

  // Explicit tab_id is an INTENTIONAL override. Per the documented contract
  // ("pass tab_id when you intentionally need a different tab than the binding"),
  // a valid explicit tab_id wins over the session's bound tab. Without this, a
  // stale/duplicate panel binding silently hijacks every call and ignores the
  // tab the caller actually asked for.
  if (explicitTabId !== undefined) {
    try {
      await chrome.tabs.get(explicitTabId);
      return { tabId: explicitTabId, source: 'explicit' };
    } catch {
      // explicit tab is stale — fall through to the session's bound tab below.
    }
  }

  if (explicitTabId !== undefined) {
    return {
      ok: false,
      error:
        `Tab ${explicitTabId} not found (closed or stale). ` +
        'Call browser_list_tabs for current tab ids across ALL Chrome windows.',
    };
  }

  // No (valid) explicit tab_id → use the session's bound tab only.
  if (sessionName) {
    const bound = await loadBoundTab(sessionName);
    if (bound) {
      try {
        await chrome.tabs.get(bound.tabId);
        return { tabId: bound.tabId, source: 'bound' };
      } catch {
        await clearBoundTab(sessionName);
        return {
          ok: false,
          error:
            `tab_not_managed: Bound tab ${bound.tabId} was closed or stale (${bound.title || bound.url}). ` +
            'Re-bind the page in DevScope, or call browser_list_tabs and pass a fresh tab_id.',
        };
      }
    }
    // Never fall back to the side-panel window's active tab — that hijacks
    // snapshots to an unrelated tab while the user works in another window.
    return {
      ok: false,
      error:
        'tab_not_managed: No tab bound for this session. Bind the target page in DevScope (Bind tab), ' +
        'or pass tab_id from browser_list_tabs.',
    };
  }

  const resolved = await resolveTab(undefined, sessionName);
  if ('error' in resolved) {
    return { ok: false, error: resolved.error };
  }
  return { tabId: resolved.tab.id, source: resolved.source === 'bound' ? 'bound' : 'active' };
}

function parseTabId(args: Record<string, unknown>): number | undefined {
  const raw = args.tab_id ?? args.tabId;
  if (raw == null || raw === '') return undefined;
  const n = Number(raw);
  return Number.isFinite(n) ? Math.trunc(n) : undefined;
}

function withTabResolution(
  result: BrowserToolResult,
  target: ResolvedTabTarget,
): BrowserToolResult {
  if (!result.ok || !result.data || typeof result.data !== 'object') {
    return result;
  }
  return {
    ...result,
    data: {
      ...(result.data as Record<string, unknown>),
      _tabResolution: {
        tabId: target.tabId,
        source: target.source,
        ...(target.ignoredTabId !== undefined
          ? { ignoredTabId: target.ignoredTabId }
          : {}),
      },
    },
  };
}

export async function executeBrowserTool(
  tool: string,
  args: Record<string, unknown>,
  sessionName?: string,
): Promise<BrowserToolResult> {
  const route = await resolveBrowseRoute(tool);
  const explicitTabId = parseTabId(args);
  const tabRes = await resolveEffectiveTabId(explicitTabId, sessionName, tool);
  if ('error' in tabRes) {
    return tabRes;
  }
  const tabTarget = tabRes as ResolvedTabTarget;
  const effectiveTabId = tabTarget.tabId >= 0 ? tabTarget.tabId : undefined;

  let result: BrowserToolResult;
  switch (tool) {
    case 'browser_get_page_info':
      result = await browserGetPageInfo(effectiveTabId);
      break;
    case 'browser_list_tabs':
      result = await browserListTabs(sessionName);
      break;
    case 'browser_navigate':
      result = await browserNavigate(String(args.url ?? ''), effectiveTabId);
      break;
    case 'browser_new_page': {
      const winId = args.window_id != null ? Number(args.window_id) : undefined;
      const active = args.active === true;
      result = await browserNewPage(String(args.url ?? 'about:blank'), winId, active);
      break;
    }
    case 'browser_screenshot':
      result = await browserScreenshot(Boolean(args.full_page), effectiveTabId);
      break;
    case 'browser_click': {
      const refRaw = args.ref ?? args.element_ref;
      const ref = refRaw != null && refRaw !== '' ? Number(refRaw) : undefined;
      result = await browserClick(String(args.selector ?? ''), effectiveTabId, Number.isFinite(ref) ? ref : undefined);
      break;
    }
    case 'browser_fill': {
      const refRaw = args.ref ?? args.element_ref;
      const ref = refRaw != null && refRaw !== '' ? Number(refRaw) : undefined;
      result = await browserFill(String(args.selector ?? ''), String(args.value ?? ''), effectiveTabId, Number.isFinite(ref) ? ref : undefined);
      break;
    }
    case 'browser_get_elements':
      result = await browserGetElements(
        String(args.selector ?? ''),
        Array.isArray(args.attributes) ? args.attributes.map(String) : undefined,
        effectiveTabId,
      );
      break;
    case 'browser_evaluate':
      result = await browserEvaluate(String(args.expression ?? ''), effectiveTabId);
      break;
    case 'browser_snapshot':
      result = await browserSnapshot(effectiveTabId);
      break;
    case 'browser_get_network':
      result = await browserGetNetwork(effectiveTabId);
      break;
    case 'browser_get_console':
      result = await browserGetConsole(Number(args.max ?? 100), effectiveTabId);
      break;
    case 'browser_highlight':
      result = await browserHighlight(
        Array.isArray(args.selectors) ? args.selectors.map(String) : [],
        Array.isArray(args.labels) ? args.labels.map(String) : [],
        effectiveTabId,
      );
      break;
    case 'browser_wait_for_selector':
      result = await browserWaitForSelector(String(args.selector ?? ''), Number(args.timeout_ms ?? 5000), effectiveTabId);
      break;
    case 'browser_wait_for_navigation':
      result = await browserWaitForNavigation(Number(args.timeout_ms ?? 10000), effectiveTabId);
      break;
    case 'browser_assert_text':
      result = await browserAssertText(
        String(args.text ?? ''),
        args.selector != null ? String(args.selector) : undefined,
        effectiveTabId,
      );
      break;
    case 'browser_scroll_to':
      result = await browserScrollTo(String(args.selector ?? ''), effectiveTabId);
      break;
    case 'browser_select_option':
      result = await browserSelectOption(String(args.selector ?? ''), String(args.value ?? ''), effectiveTabId);
      break;
    case 'browser_hover':
      result = await browserHover(String(args.selector ?? ''), effectiveTabId);
      break;
    case 'browser_key_press':
      result = await browserKeyPress(
        String(args.key ?? ''),
        args.selector != null ? String(args.selector) : undefined,
        effectiveTabId,
      );
      break;
    case 'browser_upload_file':
      result = await browserUploadFile(
        String(args.selector ?? ''),
        String(args.base64 ?? ''),
        String(args.filename ?? 'upload'),
        String(args.mime ?? 'application/octet-stream'),
        effectiveTabId,
      );
      break;
    case 'browser_focus_tab':
      result = await browserFocusTab(effectiveTabId);
      break;
    case 'linkedin_scrape_feed':
      return sendLinkedInTabMessage(effectiveTabId, {
        type: 'LINKEDIN_SCRAPE_FEED',
        maxPosts: Number(args.max_posts ?? 20),
      });
    case 'linkedin_fill_composer':
      return sendLinkedInTabMessage(effectiveTabId, {
        type: 'LINKEDIN_FILL_COMPOSER',
        text: String(args.text ?? ''),
        autoSend: Boolean(args.auto_send),
        allowSend: Boolean(args.allow_send),
      });
    case 'linkedin_fill_comment':
      return sendLinkedInTabMessage(effectiveTabId, {
        type: 'LINKEDIN_FILL_COMMENT',
        text: String(args.text ?? ''),
        postSelector: args.post_selector != null ? String(args.post_selector) : undefined,
        allowSend: Boolean(args.allow_send),
      });
    case 'linkedin_scrape_people_search':
      return sendLinkedInTabMessage(effectiveTabId, {
        type: 'SCRAPE_LINKEDIN_SEARCH_DEEP',
        maxProfiles: Number(args.max_profiles ?? 25),
        maxPages: Number(args.max_pages ?? 1),
      });
    case 'linkedin_read_search_state':
      return sendLinkedInTabMessage(effectiveTabId, {
        type: 'READ_LINKEDIN_SEARCH_STATE',
      });
    case 'linkedin_scrape_profile':
      return sendLinkedInTabMessage(effectiveTabId, {
        type: 'SCRAPE_LINKEDIN_PROFILE',
        full: args.full !== false,
        initialWait: Number(args.initial_wait ?? 2500),
      });
    case 'browser_wa_store': {
      // WhatsApp Web lives at a fixed URL — locate its tab directly.
      const waTabs = await chrome.tabs.query({ url: 'https://web.whatsapp.com/*' });
      const waTabId = waTabs.find((t) => t.id !== undefined)?.id;
      if (waTabId === undefined) {
        return {
          ok: false,
          error: 'whatsapp_not_open',
          data: { hint: 'Open web.whatsapp.com in Chrome, then retry.' },
        };
      }
      return runWaStore(
        waTabId,
        String(args.op ?? ''),
        (args.params as Record<string, unknown>) ?? {},
      );
    }
    default:
      return {
        ok: false,
        error: `Unknown browser tool: ${tool}. Reload DevScope unpacked from extension/dist after npm run build.`,
      };
  }

  if (result.ok && result.data && typeof result.data === 'object') {
    result = {
      ...result,
      data: {
        ...(result.data as Record<string, unknown>),
        _browseDriver: route.driver,
        _browseRouteReason: route.reason,
      },
    };
  }
  return withTabResolution(result, tabTarget);
}
