/**
 * service_worker.ts — MV3 background service worker.
 *
 * Responsibilities:
 *  1. Open the side panel when the extension action is clicked.
 *  2. Ensure the offscreen document (which owns all WebSockets) is alive.
 *  3. Wait for offscreen_ready before side panel sends bridge traffic.
 *
 * Side panel → offscreen uses chrome.runtime.sendMessage broadcast directly.
 * Service worker must NOT re-forward those messages (would duplicate handling).
 */

import { executeBrowserTool, pickElement } from './browser_tools';
import {
  handleAnnotationAttached,
  startAnnotateMode,
  stopAnnotateMode,
} from './annotate_mode';
import { listAllTabs } from './tab_list';
import { startRecordingHalo, stopRecordingHalo } from './recording_halo';
import { getProfileIdentity } from './profile_identity';
import type { RecorderStartMsg, RecorderStopMsg, ExecuteBrowserToolMsg } from '@/shared/messaging';
import {
  getTabCaptureStreamId,
  humanizeRecordingError,
  isRecordableUrl,
  prepareTabForRecording,
  resolveRecordTab,
} from '@/shared/recordingTab';

const OFFSCREEN_URL = chrome.runtime.getURL('offscreen.html');
const STORAGE_TOKEN_KEY = 'bridgeToken';
const PANEL_HOST_WINDOW_KEY = 'panelHostWindowId';
/** Long-lived port name the side panel opens on mount (open-panel detection). */
const PANEL_PORT_NAME = 'devscope-panel';
const ATTENTION_BADGE_TEXT = '!';
const ATTENTION_BADGE_COLOR = '#d97706';

let offscreenReadyAt = 0;
let panelHostWindowId: number | null = null;
let connectedPanelPorts = 0;

function log(...args: unknown[]): void {
  console.log('[DevScope SW]', ...args);
}

// ─── Token resolution ────────────────────────────────────────────────────────
// The offscreen document is not granted `chrome.storage` access, so it can't
// read the bridge token itself. On every wake we resolve the token (preferring
// one the side panel already pushed, falling back to storage which the service
// worker CAN read) so the offscreen WS layer always has a token — even for a
// freshly created session whose first action is `wake_offscreen`.

async function resolveToken(pushed?: string): Promise<string> {
  if (pushed) return pushed;
  try {
    const result = await chrome.storage.local.get(STORAGE_TOKEN_KEY);
    return (result[STORAGE_TOKEN_KEY] as string | undefined) ?? '';
  } catch {
    return '';
  }
}

// ─── Offscreen lifecycle ──────────────────────────────────────────────────────

async function ensureOffscreen(): Promise<void> {
  const existing = await chrome.offscreen.hasDocument();
  if (existing) return;
  log('creating offscreen document');
  await chrome.offscreen.createDocument({
    url: OFFSCREEN_URL,
    reasons: [chrome.offscreen.Reason.BLOBS, chrome.offscreen.Reason.USER_MEDIA],
    justification:
      'Maintains WebSocket connections to the local dev bridge, tab recording, and voice input',
  });
}

async function waitForOffscreenReady(timeoutMs = 5_000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (offscreenReadyAt > 0) return;
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  // MV3 SW can restart while the offscreen doc keeps running — it won't re-send
  // offscreen_ready, but the document is still usable.
  if (await chrome.offscreen.hasDocument()) {
    offscreenReadyAt = Date.now();
    log('offscreen assumed ready (document exists)');
    return;
  }
  throw new Error('offscreen did not become ready in time');
}

/** Push bridge token + Chrome profile to offscreen so WS bootstrap works without the side panel. */
async function pushBridgeCredentials(pushedToken?: string): Promise<void> {
  const token = await resolveToken(pushedToken);
  if (token) {
    await chrome.runtime.sendMessage({ kind: 'set_token', token }).catch(() => {});
  }
  const { profileId, profileLabel } = await getProfileIdentity();
  await chrome.runtime
    .sendMessage({ kind: 'set_profile', profileId, profileLabel })
    .catch(() => {});
}

/** Ensure offscreen exists, is ready, and has credentials to open bridge WebSockets. */
async function ensureOffscreenAndCredentials(pushedToken?: string): Promise<void> {
  await ensureOffscreen();
  await waitForOffscreenReady();
  await pushBridgeCredentials(pushedToken);
}

// ─── Action click → open side panel ─────────────────────────────────────────

chrome.action.onClicked.addListener((tab) => {
  if (tab.windowId === undefined) return;
  panelHostWindowId = tab.windowId;
  chrome.storage.session
    .set({ [PANEL_HOST_WINDOW_KEY]: tab.windowId })
    .catch(() => {});
  chrome.sidePanel.open({ windowId: tab.windowId }).catch(() => {});
});

// ─── Startup: ensure offscreen is ready ─────────────────────────────────────

chrome.runtime.onInstalled.addListener(() => {
  offscreenReadyAt = 0;
  ensureOffscreenAndCredentials().catch((err) => log('bridge bootstrap failed:', err));
});

chrome.runtime.onStartup.addListener(() => {
  offscreenReadyAt = 0;
  ensureOffscreenAndCredentials().catch((err) => log('bridge bootstrap failed:', err));
});

// SW can restart while offscreen keeps running — reconnect bridge without opening the panel.
void chrome.storage.session
  .get(PANEL_HOST_WINDOW_KEY)
  .then((stored) => {
    const id = stored[PANEL_HOST_WINDOW_KEY] as number | undefined;
    if (id != null) panelHostWindowId = id;
  })
  .catch(() => {});
void ensureOffscreenAndCredentials().catch((err) => log('initial bridge bootstrap failed:', err));

// ─── Attention badge (panel closed, agent needs a decision) ──────────────────

function setAttentionBadge(): void {
  chrome.action.setBadgeBackgroundColor({ color: ATTENTION_BADGE_COLOR }).catch(() => {});
  chrome.action.setBadgeText({ text: ATTENTION_BADGE_TEXT }).catch(() => {});
}

function clearAttentionBadge(): void {
  chrome.action.setBadgeText({ text: '' }).catch(() => {});
}

function notifyPermissionWhilePanelClosed(sessionName: string, title: string): void {
  setAttentionBadge();
  chrome.notifications.create(`devscope-attention-${sessionName}`, {
    type: 'basic',
    iconUrl: chrome.runtime.getURL('icon-128.png'),
    title: `DevScope — ${sessionName}`,
    message: title || 'The agent is waiting for your decision',
    priority: 2,
  });
}

chrome.runtime.onConnect.addListener((port) => {
  if (port.name !== PANEL_PORT_NAME) return;
  connectedPanelPorts++;
  clearAttentionBadge();
  port.onDisconnect.addListener(() => {
    connectedPanelPorts = Math.max(0, connectedPanelPorts - 1);
  });
});

/** Badge/notify on permission_request while closed; clear once a decision goes out. */
function handleAttentionSignals(msg: {
  kind?: string;
  sessionName?: string;
  frame?: { type?: string; kind?: string; title?: string };
}): void {
  if (msg.kind === 'bridge_frame' && msg.frame?.type === 'permission_request') {
    if (msg.frame.kind === 'permission_denied') return; // informational, no decision needed
    if (connectedPanelPorts === 0) {
      notifyPermissionWhilePanelClosed(msg.sessionName ?? '', msg.frame.title ?? '');
    }
    return;
  }
  if (msg.kind === 'send_to_bridge' && msg.frame?.type === 'permission_response') {
    clearAttentionBadge();
  }
}

// ─── Message routing ──────────────────────────────────────────────────────────

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  handleAttentionSignals(msg ?? {});

  if (msg?.kind === 'offscreen_ready') {
    offscreenReadyAt = Date.now();
    log('offscreen ready');
    return false;
  }

  if (msg?.kind === 'sw_keepalive') {
    return false;
  }

  if (msg?.kind === 'wake_offscreen') {
    const pushed = (msg as { token?: string }).token as string | undefined;
    ensureOffscreenAndCredentials(pushed)
      .then(() => sendResponse({ ok: true }))
      .catch((err: unknown) => sendResponse({ ok: false, error: String(err) }));
    return true;
  }

  if (msg?.kind === 'ensure_session_ws') {
    const sessionName = (msg as { sessionName?: string }).sessionName ?? '';
    ensureOffscreenAndCredentials()
      .then(() => chrome.runtime.sendMessage({ kind: 'ensure_session_ws', sessionName }))
      .then(() => sendResponse({ ok: true }))
      .catch((err: unknown) => sendResponse({ ok: false, error: String(err) }));
    return true;
  }

  if (msg?.kind === 'reset_session_ws') {
    const sessionName = (msg as { sessionName?: string }).sessionName ?? '';
    ensureOffscreenAndCredentials()
      .then(() => chrome.runtime.sendMessage({ kind: 'reset_session_ws', sessionName }))
      .then(() => sendResponse({ ok: true }))
      .catch((err: unknown) => sendResponse({ ok: false, error: String(err) }));
    return true;
  }

  // NOTE: no `send_to_bridge` branch here — the offscreen document receives the
  // side panel's broadcast DIRECTLY. Re-forwarding the same message made the
  // offscreen handle it twice, sending EVERY user message to the bridge twice
  // (chat-reliability C1). The panel wakes the offscreen before sending, so no
  // relay is needed.

  if (msg?.kind === 'sync_ws_keepalive') {
    ensureOffscreenAndCredentials()
      .then(() => chrome.runtime.sendMessage(msg))
      .then(() => sendResponse({ ok: true }))
      .catch((err: unknown) => sendResponse({ ok: false, error: String(err) }));
    return true;
  }

  if (msg?.kind === 'play_action_sound') {
    ensureOffscreenAndCredentials()
      .then(() => chrome.runtime.sendMessage({ kind: 'play_action_sound' }))
      .catch(() => {});
    return false;
  }

  if (msg?.kind === 'switch_to_main_tab') {
    const tabId = (msg as { tabId?: number }).tabId;
    if (typeof tabId === 'number') {
      chrome.tabs.get(tabId).then((tab) => {
        void chrome.windows.update(tab.windowId, { focused: true });
        void chrome.tabs.update(tabId, { active: true });
      }).catch(() => {});
    }
    sendResponse({ ok: true });
    return false;
  }

  if (msg?.kind === 'execute_browser_tool') {
    executeBrowserTool(
      msg.tool,
      msg.args ?? {},
      (msg as ExecuteBrowserToolMsg).sessionName,
    )
      .then((result) => sendResponse(result))
      .catch((err: unknown) => sendResponse({ ok: false, error: String(err) }));
    return true;
  }

  if (msg?.kind === 'register_panel_host') {
    const windowId = (msg as { windowId?: number }).windowId;
    if (windowId != null) {
      panelHostWindowId = windowId;
      chrome.storage.session
        .set({ [PANEL_HOST_WINDOW_KEY]: windowId })
        .catch(() => {});
    }
    sendResponse({ ok: true });
    return false;
  }

  if (msg?.kind === 'get_profile_identity') {
    getProfileIdentity()
      .then(({ profileId, profileLabel }) => sendResponse({ ok: true, profileId, profileLabel }))
      .catch((err: unknown) => sendResponse({ ok: false, error: String(err) }));
    return true;
  }

  if (msg?.kind === 'list_browser_tabs') {
    listAllTabs()
      .then((tabs) => sendResponse({ ok: true, tabs }))
      .catch((err: unknown) => sendResponse({ ok: false, error: String(err) }));
    return true;
  }

  if (msg?.kind === 'pick_element') {
    pickElement(
      (msg as { tabId?: number }).tabId,
      (msg as { sessionName?: string }).sessionName,
    )
      .then((result) => sendResponse(result))
      .catch((err: unknown) => sendResponse({ ok: false, error: String(err) }));
    return true;
  }

  if (msg?.kind === 'start_annotate_mode') {
    startAnnotateMode(
      (msg as { tabId?: number }).tabId,
      (msg as { sessionName?: string }).sessionName,
    )
      .then((result) => sendResponse(result))
      .catch((err: unknown) => sendResponse({ ok: false, error: String(err) }));
    return true;
  }

  if (msg?.kind === 'stop_annotate_mode') {
    stopAnnotateMode((msg as { tabId?: number }).tabId)
      .then((result) => sendResponse(result))
      .catch((err: unknown) => sendResponse({ ok: false, error: String(err) }));
    return true;
  }

  if (msg?.kind === 'annotation_attached') {
    const element = (msg as { element?: Record<string, unknown> }).element;
    const tabId = _sender.tab?.id;
    if (element) {
      handleAnnotationAttached(element, tabId)
        .then(() => sendResponse({ ok: true }))
        .catch((err: unknown) => sendResponse({ ok: false, error: String(err) }));
    } else {
      sendResponse({ ok: false, error: 'missing element' });
    }
    return true;
  }

  if (msg?.kind === 'start_recording') {
    const tabId = (msg as { tabId?: number }).tabId;
    handleStartRecording(tabId)
      .then(() => sendResponse({ ok: true }))
      .catch((err: unknown) => sendResponse({ ok: false, error: String(err) }));
    return true;
  }

  if (msg?.kind === 'stop_recording') {
    const stopMsg: RecorderStopMsg = { kind: 'recorder_stop' };
    chrome.runtime.sendMessage(stopMsg).catch(() => {});
    stopRecordingHalo();
    sendResponse({ ok: true });
    return false;
  }

  // Capture can also end externally (tab closed, track ended) — drop the halo.
  if (msg?.kind === 'recording_status' && (msg as { recording?: boolean }).recording === false) {
    stopRecordingHalo();
    return false;
  }

  if (msg?.kind === 'wa_draft_request') {
    const senderTabId = _sender.tab?.id;
    handleWaDraftRequest(senderTabId)
      .then((result) => sendResponse(result))
      .catch((err: unknown) => sendResponse({ ok: false, error: String(err) }));
    return true;
  }

  // bridge_frame / status flow offscreen → side panel via broadcast.
  // send_to_bridge / ensure_session_ws / etc. go side panel → offscreen directly.
  return false;
});

// ─── WhatsApp in-page draft ───────────────────────────────────────────────────

async function handleWaDraftRequest(
  senderTabId?: number,
): Promise<{ ok: boolean; suggestion?: string; error?: string }> {
  // 1. Resolve the WhatsApp tab (prefer sender tab from content script).
  const waTabId: number | undefined = senderTabId ?? await (async () => {
    const tabs = await chrome.tabs.query({ url: 'https://web.whatsapp.com/*' });
    return tabs.find((t) => t.id !== undefined)?.id;
  })();
  if (!waTabId) return { ok: false, error: 'אין טאב פתוח של WhatsApp Web' };

  // 2. Grab the active chat ID from the MAIN world (window.require is available).
  const [execRes] = await chrome.scripting.executeScript({
    target: { tabId: waTabId },
    world: 'MAIN',
    func: (): { chatId: string; chatName: string } | null => {
      const g: any = window;
      try {
        const req: any = g.require;
        if (typeof req !== 'function') return null;
        const coll = req('WAWebCollections');
        const active = coll?.Chat?.active?.() || coll?.Chat?.getActive?.();
        if (!active) return null;
        const chatId: string = active.id?._serialized || String(active.id);
        const chatName: string = active.formattedTitle || active.name || '';
        return { chatId, chatName };
      } catch {
        return null;
      }
    },
  });
  const chat = execRes?.result as { chatId: string; chatName: string } | null;
  if (!chat?.chatId) return { ok: false, error: 'פתח/י קודם צ\'אט בוואטסאפ' };

  // 3. Ask the cockpit assistant via the bridge HTTP API.
  const token = await resolveToken();
  let resp: Response;
  try {
    resp = await fetch('http://127.0.0.1:7878/wa/cockpit/ask', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        chat_id: chat.chatId,
        question: 'מה כדאי לענות? הצע ניסוח קצר ומתאים לשיחה.',
      }),
      signal: AbortSignal.timeout(90_000),
    });
  } catch (e: unknown) {
    return { ok: false, error: 'Bridge לא זמין' };
  }
  if (!resp.ok) return { ok: false, error: `Bridge HTTP ${resp.status}` };

  const data = (await resp.json()) as { ok?: boolean; data?: { answer?: string } };
  const answer = data?.data?.answer ?? '';
  if (!answer) return { ok: false, error: 'אין תשובה מהעוזר' };

  // 4. Extract "הצעה לתשובה: <text>" from the answer (the prefix the assistant uses).
  const match = answer.match(/הצעה לתשובה[:\s]+(.+)/);
  const suggestion = match
    ? match[1].trim()
    : answer.split('\n').map((l) => l.trim()).filter(Boolean).pop() ?? '';
  if (!suggestion) return { ok: false, error: 'לא נמצאה הצעה' };

  return { ok: true, suggestion };
}

// ─── Tab recording ────────────────────────────────────────────────────────────

async function handleStartRecording(
  tabId?: number,
): Promise<{ ok: boolean; error?: string }> {
  const broadcastError = (error: string) => {
    chrome.runtime
      .sendMessage({ kind: 'recording_status', recording: false, error })
      .catch(() => {});
  };

  let tabUrl: string | undefined;
  try {
    const tab =
      tabId !== undefined
        ? await chrome.tabs.get(tabId)
        : await resolveRecordTab();

    tabUrl = tab.url;
    if (!tab?.id) {
      const error = 'No recordable tab — focus a web page (not chrome://) first.';
      broadcastError(error);
      return { ok: false, error };
    }

    if (!isRecordableUrl(tabUrl)) {
      const error = humanizeRecordingError('Chrome pages cannot be captured', tabUrl);
      broadcastError(error);
      return { ok: false, error };
    }

    const streamId = await getTabCaptureStreamId(tab.id);
    log('got tabCapture streamId for tab', tab.id, tabUrl?.slice(0, 60));
    await prepareTabForRecording(tab);

    await ensureOffscreen();
    const hadDoc = await chrome.offscreen.hasDocument();
    if (!hadDoc && offscreenReadyAt === 0) {
      await waitForOffscreenReady();
    }

    const startMsg: RecorderStartMsg = { kind: 'recorder_start', streamId };
    await chrome.runtime.sendMessage(startMsg);
    startRecordingHalo(tab.id);
    return { ok: true };
  } catch (err) {
    const raw = err instanceof Error ? err.message : String(err);
    log('handleStartRecording failed:', raw, tabUrl);
    const error = humanizeRecordingError(raw, tabUrl);
    broadcastError(error);
    return { ok: false, error };
  }
}

// ─── Attention notifications → focus side panel ─────────────────────────────

chrome.notifications.onClicked.addListener((notificationId) => {
  if (!notificationId.startsWith('devscope-attention-')) return;
  void chrome.windows.getLastFocused({ populate: false }).then((win) => {
    if (win.id === undefined) return;
    chrome.sidePanel.open({ windowId: win.id }).catch(() => {});
  });
  chrome.notifications.clear(notificationId).catch(() => {});
});
