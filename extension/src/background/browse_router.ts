/**
 * browse_router.ts — pick extension vs CDP for a tool call (same tab always).
 */
import type { BrowseBackend } from '@/shared/browseBackend';
import { CDP_PREFERRED_TOOLS } from '@/shared/browseBackend';
import { loadBrowseBackend } from './browse_backend_storage';

export type ResolvedBrowseDriver = 'extension' | 'cdp';

export interface BrowseRoute {
  driver: ResolvedBrowseDriver;
  reason: string;
}

export async function resolveBrowseRoute(tool: string): Promise<BrowseRoute> {
  const pref = await loadBrowseBackend();

  if (pref === 'extension') {
    return { driver: 'extension', reason: 'user preference: This tab' };
  }

  const cdpCandidate = pref === 'cdp' || (pref === 'auto' && CDP_PREFERRED_TOOLS.has(tool));

  if (cdpCandidate) {
    try {
      if (chrome.debugger) {
        return { driver: 'cdp', reason: pref === 'cdp' ? 'user preference: CDP' : 'auto: CDP for mutating tool' };
      }
    } catch {
      /* debugger permission unavailable */
    }
    return { driver: 'extension', reason: 'CDP unavailable — extension fallback' };
  }

  return { driver: 'extension', reason: 'auto: read/light action → extension' };
}

/** @internal test helper */
export function resolveBrowseRouteSync(tool: string, pref: BrowseBackend): BrowseRoute {
  if (pref === 'extension') return { driver: 'extension', reason: 'user preference: This tab' };
  if (pref === 'cdp' || (pref === 'auto' && CDP_PREFERRED_TOOLS.has(tool))) {
    return { driver: 'cdp', reason: 'cdp route' };
  }
  return { driver: 'extension', reason: 'auto: extension' };
}
