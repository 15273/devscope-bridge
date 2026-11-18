/**
 * Filter console / network captures by tab_id and since_ts.
 * since_ts is Unix seconds, or milliseconds if the value is >= 1e12.
 */

const MS_THRESHOLD = 1_000_000_000_000;

export function normalizeSinceMs(sinceTs: number | string | undefined | null): number | null {
  if (sinceTs == null || sinceTs === '') return null;
  const value = typeof sinceTs === 'number' ? sinceTs : Number(sinceTs);
  if (!Number.isFinite(value) || value <= 0) return null;
  return value >= MS_THRESHOLD ? value : value * 1000;
}

export type ConsoleEntry = { ts?: number; wall_ts?: number; tab_id?: number; tabId?: number; text?: string; [k: string]: unknown };
export type NetworkEntry = {
  startMs?: number;
  wall_ts?: number;
  ts?: number;
  tab_id?: number;
  tabId?: number;
  timeOrigin?: number;
  [k: string]: unknown;
};

function entryTabId(entry: { tab_id?: number; tabId?: number; tab?: number }): number | undefined {
  const raw = entry.tab_id ?? entry.tabId ?? entry.tab;
  return typeof raw === 'number' && Number.isFinite(raw) ? raw : undefined;
}

function entryWallMs(entry: NetworkEntry, timeOriginMs?: number): number | undefined {
  const raw = entry.wall_ts ?? entry.ts;
  if (typeof raw === 'number' && Number.isFinite(raw)) {
    return raw >= MS_THRESHOLD ? raw : raw * 1000;
  }
  if (typeof entry.startMs === 'number' && typeof timeOriginMs === 'number') {
    return timeOriginMs + entry.startMs;
  }
  return undefined;
}

export function filterConsoleEntries(
  entries: ConsoleEntry[],
  opts: { tabId?: number; sinceTs?: number | string | null } = {},
): ConsoleEntry[] {
  const sinceMs = normalizeSinceMs(opts.sinceTs);
  const wantedTab = opts.tabId;
  const hasTabIds = entries.some((e) => entryTabId(e) != null);
  return entries.filter((entry) => {
    if (wantedTab != null && hasTabIds) {
      const tab = entryTabId(entry);
      if (tab == null || tab !== wantedTab) return false;
    }
    if (sinceMs != null) {
      const wall = entryWallMs(entry);
      if (wall == null || wall < sinceMs) return false;
    }
    return true;
  });
}

export function filterNetworkEntries(
  entries: NetworkEntry[],
  opts: { tabId?: number; sinceTs?: number | string | null; timeOriginMs?: number } = {},
): NetworkEntry[] {
  const sinceMs = normalizeSinceMs(opts.sinceTs);
  const wantedTab = opts.tabId;
  const hasTabIds = entries.some((e) => entryTabId(e) != null);
  return entries.filter((entry) => {
    if (wantedTab != null && hasTabIds) {
      const tab = entryTabId(entry);
      if (tab == null || tab !== wantedTab) return false;
    }
    if (sinceMs != null) {
      const wall = entryWallMs(entry, opts.timeOriginMs);
      if (wall == null || wall < sinceMs) return false;
    }
    return true;
  });
}
