/**
 * browser_tools_read.ts — Read/query tools: page_info, snapshot, get_elements,
 * assert_text, evaluate, get_network, get_console, highlight.
 *
 * snapshot, get_elements and assert_text inject into ALL frames so extension-
 * injected iframes are visible. evaluate, get_network, get_console and
 * highlight run in the TOP frame only.
 */

import type { BrowserToolResult } from './browser_tools_types';
import { resolveTab, isRestrictedUrl } from './tab_resolver';
import { runInTab, runInTabWithArgs, runInAllFrames } from './frame_runner';
import { storeRefMap, type RefLocator } from './ref_map';

export function unwrapInjectedError(r: BrowserToolResult): BrowserToolResult {
  if (r.ok && r.data && typeof r.data === 'object' && 'error' in (r.data as object)) {
    return { ok: false, error: String((r.data as { error: string }).error) };
  }
  return r;
}

export async function browserGetPageInfo(tabId?: number): Promise<BrowserToolResult> {
  const resolved = await resolveTab(tabId);
  if ('error' in resolved) return { ok: false, error: resolved.error };
  const tab = resolved.tab;
  const base = { tabId: tab.id, url: tab.url ?? '', title: tab.title ?? '', active: tab.active ?? false, windowId: tab.windowId };
  if (isRestrictedUrl(tab.url) || !tab.id) {
    return { ok: true, data: { ...base, restricted: true, viewport: null, scroll: null } };
  }
  const injected = await runInTab(() => ({
    url: window.location.href,
    title: document.title,
    viewport: { width: window.innerWidth, height: window.innerHeight },
    scroll: { width: document.documentElement.scrollWidth, height: document.documentElement.scrollHeight, x: window.scrollX, y: window.scrollY },
  }), tabId);
  if (!injected.ok) return { ok: true, data: { ...base, restricted: false, injectionError: injected.error } };
  return { ok: true, data: { ...base, restricted: false, ...(injected.data as Record<string, unknown>) } };
}

export async function browserSnapshot(tabId?: number): Promise<BrowserToolResult> {
  type SnapNode = { ref: number; role: string; tag: string; name: string; selector?: string; [k: string]: unknown };
  type FrameSnap = { frameUrl: string; count: number; elements: SnapNode[] };

  const a11yResult = await runInAllFrames(
    () => {
      const gen = (window as unknown as { __devscopeGenerateAccessibilityTree?: () => FrameSnap | null })
        .__devscopeGenerateAccessibilityTree;
      if (typeof gen === 'function') return gen();
      return null;
    },
    [],
    (frameResults, frameIds) => {
      const frames: Array<FrameSnap & { frameId: number }> = (frameResults as unknown[])
        .map((result, i) => (result ? { ...(result as FrameSnap), frameId: frameIds[i] } : null))
        .filter((f): f is FrameSnap & { frameId: number } => f !== null);
      const elements = frames.flatMap((f) => f.elements.map((e) => ({ ...e, frameId: f.frameId, frameUrl: f.frameUrl })));
      return {
        url: frames[0]?.frameUrl ?? '',
        count: elements.length,
        frameCount: frames.length,
        refMapVersion: 2,
        elements: elements.slice(0, 400),
      };
    },
    tabId,
  );

  if (a11yResult.ok && a11yResult.data && (a11yResult.data as { count?: number }).count) {
    const resolved = await resolveTab(tabId);
    if (!('error' in resolved) && resolved.tab.id) {
      const els = (a11yResult.data as { elements: Array<SnapNode & { frameId: number; frameUrl: string }> }).elements;
      const locators: RefLocator[] = els
        .filter((e) => e.selector && typeof e.ref === 'number')
        .map((e) => ({
          tabId: resolved.tab.id!,
          frameId: e.frameId,
          ref: e.ref,
          selector: String(e.selector),
          frameUrl: e.frameUrl,
        }));
      storeRefMap(resolved.tab.id, locators);
    }
    return a11yResult;
  }

  return runInAllFrames(
    () => {
      const MAX = 200;
      const sel = 'a,button,input,select,textarea,[role],[aria-haspopup],[aria-expanded],[data-testid],h1,h2,h3,nav,main,header,footer,form,[contenteditable="true"],[class*="awsui-"]';
      const elements: Array<Record<string, unknown>> = [];
      for (const el of Array.from(document.querySelectorAll(sel))) {
        if (elements.length >= MAX) break;
        const rect = el.getBoundingClientRect();
        const style = window.getComputedStyle(el);
        if (rect.width === 0 || rect.height === 0 || style.visibility === 'hidden' || style.display === 'none') continue;
        const item: Record<string, unknown> = {
          role: el.getAttribute('role') ?? el.tagName.toLowerCase(),
          tag: el.tagName.toLowerCase(),
          name: (el.getAttribute('aria-label') ?? el.getAttribute('placeholder') ?? el.getAttribute('alt') ?? (el.textContent ?? '').trim()).slice(0, 120),
        };
        if (el.id) item.selector = `#${CSS.escape(el.id)}`;
        const expanded = el.getAttribute('aria-expanded');
        if (expanded != null) item['aria-expanded'] = expanded;
        const controls = el.getAttribute('aria-controls');
        if (controls) item['aria-controls'] = controls;
        const haspopup = el.getAttribute('aria-haspopup');
        if (haspopup) item['aria-haspopup'] = haspopup;
        const testId = el.getAttribute('data-testid');
        if (testId) item['data-testid'] = testId;
        if (el.className && /\bawsui-/.test(String(el.className))) item.widget = 'cloudscape';
        const href = el.getAttribute('href');
        if (href) item.href = href;
        const val = (el as HTMLInputElement).value;
        if (typeof val === 'string' && val) item.value = val.slice(0, 120);
        elements.push(item);
      }
      if (elements.length === 0) return null;
      return { frameUrl: location.href, count: elements.length, elements };
    },
    [],
    (frameResults, frameIds) => {
      type FR = { frameUrl: string; count: number; elements: unknown[] };
      const frames: Array<FR & { frameId: number }> = (frameResults as unknown[])
        .map((result, i) => (result ? { ...(result as FR), frameId: frameIds[i] } : null))
        .filter((f): f is FR & { frameId: number } => f !== null);
      const elements = frames.flatMap((f) => f.elements);
      return { url: frames[0]?.frameUrl ?? '', count: elements.length, frameCount: frames.length, elements: elements.slice(0, 200) };
    },
    tabId,
  );
}

export async function browserGetElements(
  selector: string,
  attributes?: string[],
  tabId?: number,
): Promise<BrowserToolResult> {
  if (!selector) return { ok: false, error: 'selector is required' };
  return runInAllFrames(
    (sel: string, attrs: string[] | null) => {
      const nodes = Array.from(document.querySelectorAll(sel));
      if (nodes.length === 0) return null;
      return {
        frameUrl: location.href,
        count: nodes.length,
        elements: nodes.slice(0, 50).map((el, index) => {
          const item: Record<string, unknown> = { index, tag: el.tagName.toLowerCase(), text: (el.textContent ?? '').trim().slice(0, 200) };
          if (attrs && attrs.length > 0) for (const name of attrs) item[name] = el.getAttribute(name);
          return item;
        }),
      };
    },
    [selector, attributes ?? null],
    (frameResults, frameIds) => {
      type FR = { frameUrl: string; count: number; elements: unknown[] };
      const frames: Array<FR & { frameId: number }> = (frameResults as unknown[])
        .map((result, i) => (result ? { ...(result as FR), frameId: frameIds[i] } : null))
        .filter((f): f is FR & { frameId: number } => f !== null);
      const totalCount = frames.reduce((sum, f) => sum + f.count, 0);
      return { selector, count: totalCount, frames };
    },
    tabId,
  );
}

export async function browserAssertText(text: string, selector?: string, tabId?: number): Promise<BrowserToolResult> {
  if (!text) return { ok: false, error: 'text is required' };
  return runInTabWithArgs(
    (needle: string, sel: string | null) => {
      const scope = sel ? document.querySelector(sel) : document.body;
      if (sel && !scope) return { present: false, error: `Element not found: ${sel}` };
      const haystack = (scope?.textContent ?? '');
      const present = haystack.includes(needle);
      return present ? { present: true, matchedIn: sel ?? 'body' } : { present: false };
    },
    [text, selector ?? null],
    'ISOLATED',
    tabId,
  ).then(unwrapInjectedError);
}

export async function browserEvaluate(expression: string, tabId?: number): Promise<BrowserToolResult> {
  if (!expression) return { ok: false, error: 'expression is required' };
  return runInTabWithArgs(
    (code: string) => {
      // Intentional: this function is serialized and injected into the browser tab to execute user JS.
      try { return { value: eval(code) }; }
      catch (e) { return { error: e instanceof Error ? e.message : String(e) }; }
    },
    [expression],
    'ISOLATED',
    tabId,
  ).then(unwrapInjectedError);
}

export async function browserGetNetwork(tabId?: number): Promise<BrowserToolResult> {
  return runInTab(() => {
    const resources = performance.getEntriesByType('resource').slice(-150).map((e) => {
      const r = e as PerformanceResourceTiming;
      return { name: r.name, type: r.initiatorType, durationMs: Math.round(r.duration), transferSize: r.transferSize, startMs: Math.round(r.startTime) };
    });
    const nav = performance.getEntriesByType('navigation')[0] as PerformanceNavigationTiming | undefined;
    return { url: location.href, count: resources.length, navigation: nav ? { type: nav.type, durationMs: Math.round(nav.duration) } : null, resources };
  }, tabId);
}

export async function browserGetConsole(maxReturn: number, tabId?: number): Promise<BrowserToolResult> {
  return runInTabWithArgs(
    (limit: number) => {
      const KEY = '__devscopeConsole';
      const store = window as unknown as Record<string, Array<Record<string, unknown>> | undefined>;
      if (!store[KEY]) {
        const buf: Array<Record<string, unknown>> = [];
        const MAX_BUF = 500;
        store[KEY] = buf;
        const fmt = (args: unknown[]): string =>
          args.map((a) => { if (typeof a === 'string') return a; try { return JSON.stringify(a); } catch { return String(a); } }).join(' ').slice(0, 2000);
        const push = (level: string, text: string): void => { buf.push({ level, ts: Date.now(), text }); if (buf.length > MAX_BUF) buf.shift(); };
        const con = console as unknown as Record<string, (...a: unknown[]) => void>;
        for (const level of ['log', 'info', 'warn', 'error', 'debug']) {
          const orig = con[level];
          if (typeof orig !== 'function') continue;
          con[level] = (...args: unknown[]) => { push(level, fmt(args)); return orig.apply(console, args); };
        }
        window.addEventListener('error', (e) => push('error', `Uncaught: ${e.message}`));
        window.addEventListener('unhandledrejection', (e) => push('error', `UnhandledRejection: ${String((e as PromiseRejectionEvent).reason)}`));
        return { installed: true, note: 'Console capture started — logs recorded from now on. Reproduce, then read again.', count: 0, entries: [] };
      }
      const buf = store[KEY] as Array<Record<string, unknown>>;
      return { installed: false, count: buf.length, entries: buf.slice(-limit) };
    },
    [maxReturn],
    'MAIN',
    tabId,
  );
}

export async function browserHighlight(selectors: string[], labels: string[], tabId?: number): Promise<BrowserToolResult> {
  if (!selectors.length) return { ok: false, error: 'selectors is required' };
  return runInTabWithArgs(
    (sels: string[], labs: string[]) => {
      const NS = 'data-devscope-highlight';
      const SIGNAL = '#E86D13';
      document.querySelectorAll(`[${NS}]`).forEach((e) => e.remove());
      let count = 0;
      sels.forEach((sel, i) => {
        let nodes: Element[];
        try { nodes = Array.from(document.querySelectorAll(sel)); } catch { return; }
        for (const el of nodes) {
          const rect = (el as HTMLElement).getBoundingClientRect();
          if (rect.width === 0 && rect.height === 0) continue;
          const box = document.createElement('div');
          box.setAttribute(NS, '1');
          Object.assign(box.style, { position: 'fixed', left: `${rect.left}px`, top: `${rect.top}px`, width: `${rect.width}px`, height: `${rect.height}px`, border: `2px solid ${SIGNAL}`, boxSizing: 'border-box', zIndex: '2147483646', pointerEvents: 'none' } as Partial<CSSStyleDeclaration>);
          const label = labs[i];
          if (label) {
            const badge = document.createElement('div');
            badge.setAttribute(NS, '1');
            Object.assign(badge.style, { position: 'fixed', left: `${rect.left}px`, top: `${Math.max(0, rect.top - 18)}px`, background: SIGNAL, color: '#fff', font: '600 11px system-ui, sans-serif', padding: '1px 5px', zIndex: '2147483647', pointerEvents: 'none', whiteSpace: 'nowrap' } as Partial<CSSStyleDeclaration>);
            badge.textContent = label;
            document.documentElement.appendChild(badge);
          }
          document.documentElement.appendChild(box);
          count += 1;
        }
      });
      setTimeout(() => { document.querySelectorAll(`[${NS}]`).forEach((n) => n.remove()); }, 8000);
      return { highlighted: count };
    },
    [selectors, labels],
    'ISOLATED',
    tabId,
  );
}
