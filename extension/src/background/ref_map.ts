/**
 * ref_map.ts — per-tab @ref → selector locators from the latest snapshot.
 */

export interface RefLocator {
  tabId: number;
  frameId: number;
  ref: number;
  selector: string;
  frameUrl: string;
}

const byTab = new Map<number, Map<number, RefLocator>>();

export function storeRefMap(tabId: number, entries: RefLocator[]): void {
  const m = new Map<number, RefLocator>();
  for (const e of entries) m.set(e.ref, e);
  byTab.set(tabId, m);
}

export function resolveRef(tabId: number, ref: number): RefLocator | null {
  return byTab.get(tabId)?.get(ref) ?? null;
}

export function clearRefMap(tabId: number): void {
  byTab.delete(tabId);
}

/** @internal test helper */
export function _refMapSize(tabId: number): number {
  return byTab.get(tabId)?.size ?? 0;
}
