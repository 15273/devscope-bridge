/**
 * tab_list.ts — list open tabs (all Chrome windows) for picker UI and browser_list_tabs.
 */
export { listTabCatalog, type BrowserWindowSummary, type TabCatalog } from './tab_catalog';

import type { BrowserTabSummary } from '@/shared/tabBinding';
import { listTabCatalog } from './tab_catalog';

export async function listAllTabs(): Promise<BrowserTabSummary[]> {
  const { tabs } = await listTabCatalog();
  return tabs;
}
