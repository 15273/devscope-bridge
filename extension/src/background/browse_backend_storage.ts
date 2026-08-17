/**
 * browse_backend_storage.ts — persisted browse driver preference (global default).
 */
import type { BrowseBackend } from '@/shared/browseBackend';

const KEY = 'browseBackend';

export async function loadBrowseBackend(): Promise<BrowseBackend> {
  const result = await chrome.storage.local.get(KEY);
  const v = result[KEY] as BrowseBackend | undefined;
  if (v === 'extension' || v === 'cdp' || v === 'auto') return v;
  return 'auto';
}

export async function saveBrowseBackend(backend: BrowseBackend): Promise<void> {
  await chrome.storage.local.set({ [KEY]: backend });
}
