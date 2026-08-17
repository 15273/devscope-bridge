/**
 * frame_runner.ts — executeScript wrappers that work across top frame and iframes.
 *
 * runInTab / runInTabWithArgs   — inject into the TOP frame only (same as before).
 * runInAllFrames                — inject into ALL frames; results are aggregated.
 *
 * Cross-origin iframes: the manifest has <all_urls> so executeScript generally
 * succeeds. Sandboxed iframes (sandbox attribute without allow-scripts) will
 * throw; we catch per-frame and continue.
 */

import type { BrowserToolResult } from './browser_tools_types';
import { resolveTab, isRestrictedUrl } from './tab_resolver';

/** Inject fn into the top frame of the resolved tab. */
export async function runInTab<T>(
  fn: () => T,
  tabId?: number,
): Promise<BrowserToolResult> {
  const resolved = await resolveTab(tabId);
  if ('error' in resolved) return { ok: false, error: resolved.error };
  const { tab } = resolved;
  if (isRestrictedUrl(tab.url)) {
    return { ok: false, error: `Cannot script restricted page: ${tab.url ?? '(unknown)'}` };
  }
  try {
    const [result] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: fn,
    });
    return { ok: true, data: result?.result ?? null };
  } catch (err) {
    return { ok: false, error: String(err) };
  }
}

/**
 * runInFirstMatchingFrame — inject into all frames; return the first success.
 *
 * The injected fn should return `{ error?: string }` on failure so we can skip
 * frames where the selector did not match.
 */
export async function runInFirstMatchingFrame<T, A extends unknown[]>(
  fn: (...args: A) => T,
  args: A,
  world: chrome.scripting.ExecutionWorld = 'ISOLATED',
  tabId?: number,
): Promise<BrowserToolResult> {
  return runInAllFrames(
    fn,
    args,
    (frameResults, frameIds) => {
      for (let i = 0; i < frameResults.length; i++) {
        const result = frameResults[i] as Record<string, unknown>;
        if (result && typeof result === 'object' && 'error' in result && result.error) {
          continue;
        }
        return { ...(result as object), frameId: frameIds[i] };
      }
      const firstErr = frameResults.find(
        (r) => r && typeof r === 'object' && 'error' in (r as object),
      ) as { error?: string } | undefined;
      return { error: firstErr?.error ?? 'Element not found in any frame' };
    },
    tabId,
    world,
  );
}

/** Inject fn+args into the top frame of the resolved tab. */
export async function runInTabWithArgs<T, A extends unknown[]>(
  fn: (...args: A) => T,
  args: A,
  world: chrome.scripting.ExecutionWorld = 'ISOLATED',
  tabId?: number,
): Promise<BrowserToolResult> {
  const resolved = await resolveTab(tabId);
  if ('error' in resolved) return { ok: false, error: resolved.error };
  const { tab } = resolved;
  if (isRestrictedUrl(tab.url)) {
    return { ok: false, error: `Cannot script restricted page: ${tab.url ?? '(unknown)'}` };
  }
  try {
    const [result] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: fn,
      args,
      world,
    });
    return { ok: true, data: result?.result ?? null };
  } catch (err) {
    return { ok: false, error: String(err) };
  }
}

/**
 * Inject fn+args into ALL frames of the resolved tab and merge the results.
 *
 * The aggregator receives the per-frame results array and returns a combined
 * value. This lets callers decide how to merge (union elements, pick first, etc.).
 *
 * Frames that throw (e.g. sandboxed iframes) are silently skipped; the frame
 * count that was actually reached is included in the return value for diagnostics.
 */
export async function runInAllFrames<T, A extends unknown[]>(
  fn: (...args: A) => T,
  args: A,
  aggregate: (frameResults: T[], frameIds: number[]) => unknown,
  tabId?: number,
  world: chrome.scripting.ExecutionWorld = 'ISOLATED',
): Promise<BrowserToolResult> {
  const resolved = await resolveTab(tabId);
  if ('error' in resolved) return { ok: false, error: resolved.error };
  const { tab } = resolved;
  if (isRestrictedUrl(tab.url)) {
    return { ok: false, error: `Cannot script restricted page: ${tab.url ?? '(unknown)'}` };
  }
  try {
    const rawResults = await chrome.scripting.executeScript({
      target: { tabId: tab.id, allFrames: true },
      func: fn,
      args,
      world,
    });
    const frameIds: number[] = [];
    const values: T[] = [];
    for (const r of rawResults) {
      if (r.result !== undefined && r.result !== null) {
        values.push(r.result as T);
        frameIds.push(r.frameId ?? 0);
      }
    }
    return { ok: true, data: aggregate(values, frameIds) };
  } catch (err) {
    return { ok: false, error: String(err) };
  }
}
