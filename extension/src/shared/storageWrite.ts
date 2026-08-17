/**
 * storageWrite — chrome.storage.local writes that survive quota pressure.
 *
 * Without unlimitedStorage, MV3 caps local storage (~10MB). Chat-history caches
 * for dozens of sessions fill it; a bare set() then throws
 * Resource::kQuotaBytes and aborts whatever await chain called it (send path).
 */

const HISTORY_KEY_PREFIX = 'session.history.';

export function isQuotaExceededError(err: unknown): boolean {
  const msg = err instanceof Error ? err.message : String(err);
  return /quota/i.test(msg) || /QUOTA_BYTES/i.test(msg);
}

/** Drop largest session.history.* caches to free space. Returns keys removed. */
export async function pruneChatHistoryCache(keepSession?: string): Promise<string[]> {
  const all = await chrome.storage.local.get(null);
  const keepKey = keepSession ? HISTORY_KEY_PREFIX + keepSession : null;
  const ranked = Object.keys(all)
    .filter((k) => k.startsWith(HISTORY_KEY_PREFIX) && k !== keepKey)
    .map((k) => {
      try {
        return { k, size: JSON.stringify(all[k] ?? '').length };
      } catch {
        return { k, size: 1 };
      }
    })
    .sort((a, b) => b.size - a.size);

  const toRemove = ranked.slice(0, Math.max(8, Math.ceil(ranked.length / 3))).map((r) => r.k);
  if (toRemove.length === 0) return [];
  await chrome.storage.local.remove(toRemove);
  return toRemove;
}

/** Remove every session.history.* key (last resort). */
export async function clearAllChatHistoryCaches(): Promise<number> {
  const all = await chrome.storage.local.get(null);
  const keys = Object.keys(all).filter((k) => k.startsWith(HISTORY_KEY_PREFIX));
  if (keys.length === 0) return 0;
  await chrome.storage.local.remove(keys);
  return keys.length;
}

/**
 * chrome.storage.local.set with prune+retry on quota exceeded.
 * Still throws if the write cannot succeed after clearing history caches.
 */
export async function safeLocalSet(
  items: Record<string, unknown>,
  opts?: { keepSession?: string },
): Promise<void> {
  try {
    await chrome.storage.local.set(items);
    return;
  } catch (err) {
    if (!isQuotaExceededError(err)) throw err;
  }

  const pruned = await pruneChatHistoryCache(opts?.keepSession);
  console.warn('[DevScope] storage quota — pruned history keys:', pruned.length);

  try {
    await chrome.storage.local.set(items);
    return;
  } catch (err) {
    if (!isQuotaExceededError(err)) throw err;
  }

  const cleared = await clearAllChatHistoryCaches();
  console.warn('[DevScope] storage quota — cleared all history caches:', cleared);
  await chrome.storage.local.set(items);
}
