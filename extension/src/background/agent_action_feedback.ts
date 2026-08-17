/**
 * agent_action_feedback.ts — visual ripple + optional sound after mutating browser tools.
 */

async function uiPrefs(): Promise<{ showClickHighlights: boolean; actionSound: boolean }> {
  const r = await chrome.storage.local.get('uiPrefs');
  const p = r.uiPrefs as { showClickHighlights?: boolean; actionSound?: boolean } | undefined;
  return {
    showClickHighlights: p?.showClickHighlights !== false,
    actionSound: p?.actionSound === true,
  };
}

export async function notifyAgentAction(
  tabId: number,
  selector?: string,
  coords?: { x: number; y: number },
): Promise<void> {
  const prefs = await uiPrefs();
  if (prefs.showClickHighlights) {
    try {
      await chrome.tabs.sendMessage(tabId, {
        kind: 'show_agent_action',
        selector,
        x: coords?.x,
        y: coords?.y,
      });
    } catch {
      /* restricted or no content script */
    }
  }
  if (prefs.actionSound) {
    chrome.runtime.sendMessage({ kind: 'play_action_sound' }).catch(() => {});
  }
}
