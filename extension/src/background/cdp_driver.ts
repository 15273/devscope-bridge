/**
 * cdp_driver.ts — Chrome DevTools Protocol on the user's tab (Layer B).
 * Attach per-action to minimize the "DevScope is debugging" banner.
 */
import type { BrowserToolResult } from './browser_tools_types';

const PROTO_VERSION = '1.3';
const attached = new Set<number>();

async function attachTab(tabId: number): Promise<void> {
  if (attached.has(tabId)) return;
  await chrome.debugger.attach({ tabId }, PROTO_VERSION);
  attached.add(tabId);
}

async function detachTab(tabId: number): Promise<void> {
  if (!attached.has(tabId)) return;
  try {
    await chrome.debugger.detach({ tabId });
  } catch {
    /* already detached */
  }
  attached.delete(tabId);
}

async function sendCommand<T = unknown>(
  tabId: number,
  method: string,
  params?: Record<string, unknown>,
): Promise<T> {
  await attachTab(tabId);
  const result = await chrome.debugger.sendCommand({ tabId }, method, params);
  return result as T;
}

export async function cdpClick(tabId: number, x: number, y: number): Promise<BrowserToolResult> {
  try {
    await sendCommand(tabId, 'Input.dispatchMouseEvent', {
      type: 'mousePressed',
      x,
      y,
      button: 'left',
      clickCount: 1,
    });
    await sendCommand(tabId, 'Input.dispatchMouseEvent', {
      type: 'mouseReleased',
      x,
      y,
      button: 'left',
      clickCount: 1,
    });
    return { ok: true, data: { backend: 'cdp', x, y } };
  } catch (err) {
    return { ok: false, error: String(err) };
  } finally {
    await detachTab(tabId);
  }
}

export async function cdpClickSelector(tabId: number, selector: string): Promise<BrowserToolResult> {
  try {
    const box = await sendCommand<{ result: { value?: { x: number; y: number } } }>(
      tabId,
      'Runtime.evaluate',
      {
        expression: `(function(){
          const el = document.querySelector(${JSON.stringify(selector)});
          if (!el) return null;
          const r = el.getBoundingClientRect();
          return { x: r.left + r.width/2, y: r.top + r.height/2 };
        })()`,
        returnByValue: true,
      },
    );
    const pt = box?.result?.value;
    if (!pt) return { ok: false, error: `CDP: element not found: ${selector}` };
    return cdpClick(tabId, pt.x, pt.y);
  } catch (err) {
    return { ok: false, error: String(err) };
  }
}

export async function cdpFillSelector(
  tabId: number,
  selector: string,
  value: string,
): Promise<BrowserToolResult> {
  try {
    const res = await sendCommand<{ result: { value?: { ok?: boolean; error?: string } } }>(
      tabId,
      'Runtime.evaluate',
      {
        expression: `(function(){
          const el = document.querySelector(${JSON.stringify(selector)});
          if (!el) return { error: 'not found' };
          el.focus();
          el.value = ${JSON.stringify(value)};
          el.dispatchEvent(new Event('input', { bubbles: true }));
          el.dispatchEvent(new Event('change', { bubbles: true }));
          return { ok: true };
        })()`,
        returnByValue: true,
      },
    );
    const v = res?.result?.value;
    if (!v?.ok) return { ok: false, error: v?.error ?? 'CDP fill failed' };
    return { ok: true, data: { backend: 'cdp', selector, value } };
  } catch (err) {
    return { ok: false, error: String(err) };
  } finally {
    await detachTab(tabId);
  }
}

export async function cdpScreenshot(
  tabId: number,
  fullPage: boolean,
): Promise<BrowserToolResult> {
  try {
    const data = await sendCommand<{ data?: string }>(tabId, 'Page.captureScreenshot', {
      format: 'jpeg',
      quality: 72,
      captureBeyondViewport: fullPage,
    });
    if (!data?.data) return { ok: false, error: 'CDP screenshot returned no data' };
    const dataUrl = `data:image/jpeg;base64,${data.data}`;
    return { ok: true, data: { dataUrl, fullPage, backend: 'cdp' } };
  } catch (err) {
    return { ok: false, error: String(err) };
  } finally {
    await detachTab(tabId);
  }
}
