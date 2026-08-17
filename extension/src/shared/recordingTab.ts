/**
 * recordingTab.ts — resolve which browser tab to capture for DevScope recording.
 *
 * When the side panel has focus, tabs.query({ active: true }) can miss the page
 * tab. Prefer the side panel's host window (same as browser tools), then scan
 * the last-focused window for the first recordable tab.
 */

const RESTRICTED_URL = /^(chrome|chrome-extension|devtools|edge):\/\//i;
const PANEL_HOST_WINDOW_KEY = 'panelHostWindowId';

export function isRecordableUrl(url: string | undefined): url is string {
  if (!url) return false;
  if (RESTRICTED_URL.test(url)) return false;
  if (url.startsWith('about:')) return false;
  return true;
}

async function activeTabInHostWindow(): Promise<chrome.tabs.Tab | undefined> {
  try {
    const stored = await chrome.storage.session.get(PANEL_HOST_WINDOW_KEY);
    const hostWindowId = stored[PANEL_HOST_WINDOW_KEY] as number | undefined;
    if (hostWindowId == null) return undefined;
    const [hostTab] = await chrome.tabs.query({ active: true, windowId: hostWindowId });
    return hostTab;
  } catch {
    return undefined;
  }
}

/** Tab to record: active page tab in the side panel's host window when possible. */
export async function resolveRecordTab(): Promise<chrome.tabs.Tab> {
  const hostTab = await activeTabInHostWindow();
  if (hostTab?.id && isRecordableUrl(hostTab.url)) {
    return hostTab;
  }

  const [focused] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  if (focused?.id && isRecordableUrl(focused.url)) {
    return focused;
  }

  const win = await chrome.windows.getLastFocused({ populate: true });
  const tabs = win.tabs ?? [];
  const candidate =
    tabs.find((t) => t.active && isRecordableUrl(t.url)) ??
    tabs.find((t) => isRecordableUrl(t.url));
  if (!candidate?.id) {
    throw new Error('No recordable tab — focus a web page (not chrome://) first.');
  }
  return candidate;
}

/** Focus the target tab/window so tabCapture can bind to it from the side panel. */
export async function prepareTabForRecording(tab: chrome.tabs.Tab): Promise<void> {
  if (!tab.id || tab.windowId === undefined) return;
  await chrome.windows.update(tab.windowId, { focused: true });
  await chrome.tabs.update(tab.id, { active: true });
  await new Promise((resolve) => setTimeout(resolve, 80));
}

export function humanizeRecordingError(raw: string, tabUrl?: string): string {
  const hint = tabUrl ? ` (${tabUrl.slice(0, 72)})` : '';
  const pageIsNormal = isRecordableUrl(tabUrl);

  if (/devtools/i.test(raw)) {
    if (pageIsNormal) {
      return (
        'Chrome cannot record while DevTools is open on that tab. ' +
        'Close DevTools (F12), click the page tab once, then press Record again.' +
        hint
      );
    }
    return (
      'Cannot record Chrome internal pages (chrome://, DevTools). ' +
      'Open a normal website (http/https) and try again.' +
      hint
    );
  }

  if (/chrome pages cannot be captured|chrome:\/\//i.test(raw)) {
    if (pageIsNormal) {
      return (
        'Chrome blocked tab capture on that page. Click the page tab once, ' +
        'click the DevScope toolbar icon, then press Record again.' +
        hint
      );
    }
    return (
      'Cannot record Chrome internal pages (chrome://, DevTools). ' +
      'Open a normal website (http/https) and try again.' +
      hint
    );
  }

  if (/not been invoked|activeTab/i.test(raw)) {
    return (
      'Chrome needs the extension invoked on that tab: click the page tab once, ' +
      'click the DevScope toolbar icon, then press Record again.' +
      hint
    );
  }
  if (/No recordable tab/i.test(raw)) {
    return 'No recordable tab — open a normal website (not chrome://) in this window first.';
  }
  return raw;
}

/**
 * Obtain a tabCapture stream id. Must run in the side panel during the click
 * handler so Chrome keeps the user-gesture context (SW async handlers lose it).
 */
export function getTabCaptureStreamId(tabId: number): Promise<string> {
  return new Promise((resolve, reject) => {
    chrome.tabCapture.getMediaStreamId({ targetTabId: tabId }, (streamId) => {
      const err = chrome.runtime.lastError;
      if (err) {
        reject(new Error(err.message ?? 'tabCapture failed'));
        return;
      }
      if (!streamId) {
        reject(new Error('tabCapture returned empty stream id'));
        return;
      }
      resolve(streamId);
    });
  });
}
