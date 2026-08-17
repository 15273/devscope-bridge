/**
 * pick_element.ts — user-initiated cross-frame element picker.
 *
 * Injects a crosshair overlay into every frame of the target tab and races
 * them — the first click (or Esc) wins. This lets users pick elements inside
 * iframes, not just the top document.
 */

import type { BrowserToolResult } from './browser_tools_types';
import { resolveTabForUserGesture, isRestrictedUrl } from './tab_resolver';
import { captureElementSnippet } from './elementScreenshot';

/** Injected into each frame; must be self-contained (no closures). */
function pickerInjected(): Promise<Record<string, unknown>> {
  return new Promise<Record<string, unknown>>((resolve) => {
    const NS = 'data-devscope-picker';
    const PREV = 'data-ds-prev-outline';
    const SIGNAL = '#E86D13';
    const w = window as unknown as { __dsPickerCleanup?: () => void };
    if (typeof w.__dsPickerCleanup === 'function') {
      try {
        w.__dsPickerCleanup();
      } catch {
        /* ignore */
      }
    }
    const restoreOutline = (el: HTMLElement): void => {
      el.style.outline = el.getAttribute(PREV) ?? '';
      el.removeAttribute(PREV);
    };

    const buildSelector = (el: Element): string => {
      if (el.id) return `#${CSS.escape(el.id)}`;
      const parts: string[] = [];
      let cur: Element | null = el;
      while (cur && cur !== document.body && cur !== document.documentElement) {
        const tag = cur.tagName.toLowerCase();
        const parent: Element | null = cur.parentElement;
        if (!parent) {
          parts.unshift(tag);
          break;
        }
        const siblings = Array.from(parent.children).filter((c) => c.tagName === cur!.tagName);
        parts.unshift(siblings.length === 1 ? tag : `${tag}:nth-of-type(${siblings.indexOf(cur) + 1})`);
        if (document.querySelectorAll(parts.join(' > ')).length === 1) break;
        cur = parent;
      }
      return parts.length ? parts.join(' > ') : el.tagName.toLowerCase();
    };

    const banner = document.createElement('div');
    banner.setAttribute(NS, '1');
    Object.assign(banner.style, {
      position: 'fixed',
      top: '0',
      left: '0',
      right: '0',
      zIndex: '2147483647',
      background: SIGNAL,
      color: '#fff',
      font: '600 13px system-ui, sans-serif',
      textAlign: 'center',
      padding: '8px',
      pointerEvents: 'none',
    } as Partial<CSSStyleDeclaration>);
    banner.textContent = 'DevScope · click an element to inspect · Esc to cancel';
    document.documentElement.appendChild(banner);
    document.body.style.cursor = 'crosshair';

    const cleanup = (): void => {
      document.querySelectorAll(`[${NS}]`).forEach((e) => e.remove());
      document.removeEventListener('mousemove', onMove, true);
      document.removeEventListener('click', onClick, true);
      document.removeEventListener('keydown', onKey, true);
      document.querySelectorAll<HTMLElement>(`[${PREV}]`).forEach(restoreOutline);
      document.body.style.cursor = '';
      w.__dsPickerCleanup = undefined;
    };
    w.__dsPickerCleanup = cleanup;

    function onMove(e: MouseEvent): void {
      const t = e.target as HTMLElement;
      if (!t || t.getAttribute(NS)) return;
      document.querySelectorAll<HTMLElement>(`[${PREV}]`).forEach((el) => {
        if (el !== t) restoreOutline(el);
      });
      if (!t.hasAttribute(PREV)) t.setAttribute(PREV, t.style.outline);
      t.style.outline = `2px solid ${SIGNAL}`;
    }

    const computeAriaName = (el: HTMLElement): string | null => {
      const label = el.getAttribute('aria-label');
      if (label) return label;
      const labelledBy = el.getAttribute('aria-labelledby');
      if (labelledBy) {
        const ref = document.getElementById(labelledBy);
        if (ref) return (ref.textContent ?? '').trim() || null;
      }
      const alt = el.getAttribute('alt');
      if (alt) return alt;
      const title = el.getAttribute('title');
      if (title) return title;
      const text = (el.textContent ?? '').trim();
      return text ? text.slice(0, 120) : null;
    };

    function onClick(e: MouseEvent): void {
      const t = e.target as HTMLElement;
      if (!t || t.getAttribute(NS)) return;
      e.preventDefault();
      e.stopPropagation();
      const rect = t.getBoundingClientRect();
      const style = window.getComputedStyle(t);
      const inViewport =
        rect.top >= 0 &&
        rect.left >= 0 &&
        rect.bottom <= window.innerHeight &&
        rect.right <= window.innerWidth;
      const chain: string[] = [];
      let node: Element | null = t;
      while (node && node !== document.body && node !== document.documentElement && chain.length < 6) {
        const tag = node.tagName.toLowerCase();
        const id = node.id ? `#${node.id}` : '';
        const cls = Array.from(node.classList)
          .slice(0, 3)
          .map((c) => `.${c}`)
          .join('');
        chain.unshift(`${tag}${id}${cls}`);
        node = node.parentElement;
      }
      const editRef = `ref-${Date.now().toString(36)}-${Math.floor(Math.random() * 1e4)}`;
      t.setAttribute('data-edit-ref', editRef);

      const info: Record<string, unknown> = {
        selector: buildSelector(t),
        tag: t.tagName.toLowerCase(),
        text: (t.textContent ?? '').trim().slice(0, 200),
        ariaRole: t.getAttribute('role'),
        ariaName: computeAriaName(t),
        href: t.getAttribute('href'),
        outerHTML: (t.outerHTML ?? '').slice(0, 500),
        boundingBox: {
          x: Math.round(rect.x),
          y: Math.round(rect.y),
          width: Math.round(rect.width),
          height: Math.round(rect.height),
        },
        inViewport,
        cssSnapshot: {
          color: style.color,
          backgroundColor: style.backgroundColor,
          fontSize: style.fontSize,
          fontWeight: style.fontWeight,
          display: style.display,
          position: style.position,
        },
        domChain: chain,
        editRef,
        frameUrl: location.href,
      };
      cleanup();
      resolve(info);
    }

    function onKey(e: KeyboardEvent): void {
      if (e.key === 'Escape') {
        cleanup();
        resolve({ cancelled: true });
      }
    }

    document.addEventListener('mousemove', onMove, true);
    document.addEventListener('click', onClick, true);
    document.addEventListener('keydown', onKey, true);
  });
}

function cleanupAllFrames(tabId: number): void {
  chrome.scripting
    .executeScript({
      target: { tabId, allFrames: true },
      func: () => {
        const w = window as unknown as { __dsPickerCleanup?: () => void };
        if (typeof w.__dsPickerCleanup === 'function') {
          try {
            w.__dsPickerCleanup();
          } catch {
            /* ignore */
          }
        }
      },
    })
    .catch(() => {});
}

export async function pickElement(tabId?: number, sessionName?: string): Promise<BrowserToolResult> {
  const resolved = await resolveTabForUserGesture(tabId, sessionName);
  if ('error' in resolved) return { ok: false, error: resolved.error };
  const { tab } = resolved;
  if (isRestrictedUrl(tab.url)) {
    return {
      ok: false,
      error: `Cannot script restricted page: ${tab.url ?? '(unknown)'}`,
    };
  }

  const frames = await chrome.webNavigation.getAllFrames({ tabId: tab.id });
  const frameIds = frames?.length ? frames.map((f) => f.frameId) : [0];

  const runInFrame = (frameId: number): Promise<Record<string, unknown> | undefined> =>
    chrome.scripting
      .executeScript({
        target: { tabId: tab.id, frameIds: [frameId] },
        func: pickerInjected,
      })
      .then(([r]) => r?.result as Record<string, unknown> | undefined);

  try {
    const result = await Promise.race(frameIds.map(runInFrame));
    cleanupAllFrames(tab.id);
    if (!result) return { ok: false, error: 'Picker returned no result' };
    if (!result.cancelled && result.boundingBox && typeof result.boundingBox === 'object') {
      const box = result.boundingBox as { x: number; y: number; width: number; height: number };
      const snippet = await captureElementSnippet(tab.id, tab.windowId, box);
      if (snippet) result.screenshotSnippet = snippet;
    }
    return { ok: true, data: result };
  } catch (err) {
    cleanupAllFrames(tab.id);
    return { ok: false, error: String(err) };
  }
}
