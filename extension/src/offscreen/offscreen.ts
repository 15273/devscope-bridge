/**
 * offscreen.ts — Offscreen document owning all WebSocket connections.
 *
 * Maintains a Map<sessionName, WebSocket> — one WS per session,
 * lazily created on first send or explicit ensure_session_ws.
 * Each WS has its own exponential-backoff reconnect loop.
 */

import type { BridgeInbound, BridgeOutbound, BrowserResult, ToolCall } from '@/shared/frames';
import type {
  BridgeFrameMsg,
  SendToBridgeMsg,
  UpdateTokenMsg,
  SetTokenMsg,
  SetProfileMsg,
  EnsureSessionWsMsg,
  CloseSessionWsMsg,
  SyncWsKeepaliveMsg,
  ResetSessionWsMsg,
  RecorderStartMsg,
  RecorderStopMsg,
  ExecuteBrowserToolMsg,
} from '@/shared/messaging';
import { startRecording, stopRecording } from './recorder';
import { startSpeechRecognition, stopSpeechRecognition } from './speechRecognitionHost';
import { isPersistentAutomationSession } from '@/shared/sessionNames';
import { createFrameBatcher, type FrameBatcher } from '@/shared/frameBatch';

const BRIDGE_BASE_WS = 'ws://127.0.0.1:7878';
const BRIDGE_BASE_HTTP = 'http://127.0.0.1:7878';
const STORAGE_TOKEN_KEY = 'bridgeToken';

const BACKOFF_INITIAL_MS = 1_000;
const BACKOFF_MAX_MS = 30_000;
const SESSIONS_POLL_MS = 45_000;
/** Must finish before bridge /actions timeout (30s). */
const TOOL_EXECUTE_TIMEOUT_MS = 25_000;
/** If CONNECTING hangs longer than this, tear down and retry (Chrome/offscreen stall). */
const CONNECTING_STUCK_MS = 5_000;
/** Cap eager bootstrap WS opens — worker/mgr sockets connect on demand. */
const MAX_BOOTSTRAP_WS = 48;
/** Max time to wait for a session WS before failing the send. */
const WS_OPEN_TIMEOUT_MS = 20_000;
/** Close leftover sockets not in keepOpen (see sweepIdleUserSessions). */
const IDLE_SWEEP_MS = 60_000;

interface SessionWs {
  ws: WebSocket | null;
  backoffMs: number;
  reconnectAttempts: number;
  reconnectTimer: ReturnType<typeof setTimeout> | null;
  closed: boolean;
  pending: BridgeOutbound[];
  connectStartedAt: number | null;
  lastActivityAt: number;
  batcher: FrameBatcher;
}

const sessions = new Map<string, SessionWs>();
/** User-chat sessions allowed to hold/reopen WS; automation sessions are always kept. */
const keepOpenSessions = new Set<string>();

function log(...args: unknown[]): void {
  console.log('[DevScope offscreen]', ...args);
}

// ─── Token ────────────────────────────────────────────────────────────────────
//
// Offscreen documents are only granted the `chrome.runtime` messaging API —
// `chrome.storage` is NOT exposed here (per the Chrome offscreen-document spec),
// so reading `chrome.storage.local` throws "Cannot read properties of undefined".
// The token is therefore PUSHED in by the side panel / service worker and cached
// in this module-level variable. `getToken()` never touches `chrome.storage`
// unless it actually exists, and never throws.

let cachedToken = '';

// Chrome profile identity (pushed by the service worker via `set_profile`).
// Included in the WS `hello` frame so the bridge can route across profiles.
let cachedProfileId = '';
let cachedProfileLabel = '';

function sendHello(ws: WebSocket): void {
  if (!cachedProfileId || ws.readyState !== WebSocket.OPEN) return;
  try {
    ws.send(JSON.stringify({
      type: 'hello',
      profile_id: cachedProfileId,
      profile_label: cachedProfileLabel,
    }));
  } catch {
    /* non-fatal — bridge falls back to per-session profile */
  }
}

function broadcastHello(): void {
  for (const entry of sessions.values()) {
    if (entry.ws) sendHello(entry.ws);
  }
}

function storageLocal(): chrome.storage.StorageArea | undefined {
  return (chrome as { storage?: { local?: chrome.storage.StorageArea } }).storage?.local;
}

async function getToken(): Promise<string> {
  if (cachedToken) return cachedToken;
  const local = storageLocal();
  if (!local) return cachedToken;
  try {
    const result = await local.get(STORAGE_TOKEN_KEY);
    const stored = (result[STORAGE_TOKEN_KEY] as string | undefined) ?? '';
    if (stored) cachedToken = stored;
  } catch {
    // chrome.storage unavailable in this context — rely on the pushed token.
  }
  return cachedToken;
}

function setCachedToken(token: string): void {
  cachedToken = token ?? '';
}

// ─── Per-session WS management ───────────────────────────────────────────────

function getOrCreateEntry(sessionName: string): SessionWs {
  let entry = sessions.get(sessionName);
  if (!entry) {
    entry = {
      ws: null,
      backoffMs: BACKOFF_INITIAL_MS,
      reconnectAttempts: 0,
      reconnectTimer: null,
      closed: false,
      pending: [],
      connectStartedAt: null,
      lastActivityAt: Date.now(),
      batcher: createFrameBatcher((frame) => {
        const msg: BridgeFrameMsg = { kind: 'bridge_frame', sessionName, frame: frame as BridgeInbound };
        chrome.runtime.sendMessage(msg).catch(() => {});
      }),
    };
    sessions.set(sessionName, entry);
  }
  return entry;
}

function touchSessionActivity(sessionName: string): void {
  const entry = sessions.get(sessionName);
  if (entry) entry.lastActivityAt = Date.now();
}

function shouldStayConnected(sessionName: string): boolean {
  if (isPersistentAutomationSession(sessionName)) return true;
  return keepOpenSessions.has(sessionName);
}

function shouldBootstrapConnect(sessionName: string): boolean {
  if (!isPersistentAutomationSession(sessionName)) return false;
  if (sessions.size >= MAX_BOOTSTRAP_WS) return false;
  return true;
}

function applyWsKeepalive(keepOpen: string[]): void {
  keepOpenSessions.clear();
  for (const name of keepOpen) keepOpenSessions.add(name);
  log('ws keepalive:', keepOpen.length, 'sessions');
  for (const name of [...sessions.keys()]) {
    if (!shouldStayConnected(name)) {
      log('ws keepalive: closing idle user session', name);
      closeSessionWs(name);
    }
  }
}

function sweepIdleUserSessions(): void {
  // Never drop keepOpen membership here — that used to leave the active chat
  // permanently offline (reconnect skipped because shouldStayConnected=false)
  // while HTTP polls still worked and the UI showed "Reconnecting…" for hours.
  // applyWsKeepalive already closes sockets removed from keepOpen; this sweep
  // only cleans leftovers.
  for (const [name, entry] of sessions.entries()) {
    if (isPersistentAutomationSession(name)) continue;
    if (shouldStayConnected(name)) continue;
    if (entry.ws || sessions.has(name)) {
      log('ws idle sweep: closing non-keepOpen', name);
      closeSessionWs(name);
    }
  }
}

function closeWsEntry(entry: SessionWs): void {
  if (entry.reconnectTimer !== null) {
    clearTimeout(entry.reconnectTimer);
    entry.reconnectTimer = null;
  }
  try {
    entry.ws?.close();
  } catch {
    /* ignore */
  }
  entry.ws = null;
  entry.connectStartedAt = null;
}

function resetSessionConnection(sessionName: string, token: string): void {
  keepOpenSessions.add(sessionName);
  const entry = sessions.get(sessionName);
  if (entry) {
    entry.closed = false;
    closeWsEntry(entry);
    entry.backoffMs = BACKOFF_INITIAL_MS;
  }
  connect(sessionName, token);
}

function connect(sessionName: string, token: string): void {
  if (!token) {
    log('connect skipped — no token for', sessionName);
    return;
  }
  if (!shouldStayConnected(sessionName)) {
    log('connect skipped — user session not in keepOpen:', sessionName);
    return;
  }
  const entry = getOrCreateEntry(sessionName);
  if (entry.closed) {
    log('connect skipped — session was closed:', sessionName);
    return;
  }
  if (entry.ws?.readyState === WebSocket.OPEN) {
    log('connect skipped — WS already OPEN for', sessionName);
    return;
  }
  if (entry.ws?.readyState === WebSocket.CONNECTING) {
    const stuckMs = entry.connectStartedAt ? Date.now() - entry.connectStartedAt : 0;
    if (stuckMs < CONNECTING_STUCK_MS) {
      log('connect skipped — WS CONNECTING for', sessionName, `(${stuckMs}ms)`);
      return;
    }
    log('connect — WS stuck CONNECTING, resetting:', sessionName);
    closeWsEntry(entry);
  }

  const url = `${BRIDGE_BASE_WS}/ws/${sessionName}?token=${encodeURIComponent(token)}`;
  log('opening WS:', `${BRIDGE_BASE_WS}/ws/${sessionName}?token=***`);
  const ws = new WebSocket(url);
  entry.ws = ws;
  entry.connectStartedAt = Date.now();

  ws.onopen = () => {
    log('WS open:', sessionName, '— flushing', entry.pending.length, 'pending frames');
    entry.connectStartedAt = null;
    entry.lastActivityAt = Date.now();
    entry.backoffMs = BACKOFF_INITIAL_MS;
    entry.reconnectAttempts = 0;
    sendHello(ws);
    notifyStatus(sessionName, true);
    while (entry.pending.length > 0) {
      const frame = entry.pending.shift()!;
      ws.send(JSON.stringify(frame));
    }
  };

  ws.onmessage = (event: MessageEvent) => {
    entry.lastActivityAt = Date.now();
    let raw: Record<string, unknown>;
    try {
      raw = JSON.parse(event.data as string) as Record<string, unknown>;
    } catch {
      return;
    }

    if (raw.type === 'tool_call') {
      void handleToolCall(entry, raw as unknown as ToolCall);
      return;
    }

    if (raw.type === 'task_digest' || raw.type === 'task_update' || raw.type === 'approval_request') {
      chrome.runtime.sendMessage({ kind: 'task_board_event', event: raw }).catch(() => {});
      return;
    }

    const frame = raw as unknown as BridgeInbound;
    entry.batcher.push(frame);
  };

  ws.onerror = () => {
    log('WS error:', sessionName);
    entry.batcher.flush();
    notifyStatus(sessionName, false);
  };

  ws.onclose = (event) => {
    log('WS closed:', sessionName, 'code:', event.code, 'reason:', event.reason || '(none)');
    entry.batcher.flush();
    entry.ws = null;
    entry.connectStartedAt = null;
    if (!entry.closed) {
      notifyStatus(sessionName, false);
      scheduleReconnect(sessionName);
    }
  };
}

function scheduleReconnect(sessionName: string): void {
  if (!shouldStayConnected(sessionName)) {
    log('reconnect skipped — not keepOpen:', sessionName);
    closeSessionWs(sessionName);
    return;
  }
  const entry = sessions.get(sessionName);
  if (!entry || entry.closed || entry.reconnectTimer !== null) return;
  entry.reconnectTimer = setTimeout(async () => {
    if (!entry || entry.closed) return;
    entry.reconnectTimer = null;
    entry.reconnectAttempts += 1;
    notifyStatus(sessionName, false, entry.reconnectAttempts);
    const freshToken = await getToken();
    connect(sessionName, freshToken);
    entry.backoffMs = Math.min(entry.backoffMs * 2, BACKOFF_MAX_MS);
  }, entry.backoffMs);
}

function notifyStatus(sessionName: string, connected: boolean, reconnectAttempt?: number): void {
  const msg = { kind: 'status', sessionName, connected, reconnectAttempt } as const;
  chrome.runtime.sendMessage(msg).catch(() => {});
}

function broadcastToolActivity(
  call: ToolCall,
  phase: 'start' | 'done',
  ok?: boolean,
  summary?: string,
): void {
  try {
    chrome.runtime
      .sendMessage({
        kind: 'tool_activity',
        sessionName: call.session,
        actionId: call.action_id,
        tool: call.tool,
        phase,
        ok,
        summary,
      })
      .catch(() => {});
  } catch {
    // A failed broadcast must never break tool execution.
  }
}

function summarizeToolResult(result: { ok: boolean; error?: string }): string {
  if (!result.ok) return result.error ?? 'failed';
  return 'ok';
}

/** MV3 service worker can sleep; never hang a tool_call forever. */
function sendRuntimeMessage<T>(payload: unknown, timeoutMs: number): Promise<T> {
  return new Promise((resolve, reject) => {
    let settled = false;
    const timer = window.setTimeout(() => {
      if (settled) return;
      settled = true;
      reject(new Error(`Extension service worker did not respond within ${timeoutMs}ms`));
    }, timeoutMs);

    const finish = (fn: () => void): void => {
      if (settled) return;
      settled = true;
      window.clearTimeout(timer);
      fn();
    };

    try {
      chrome.runtime.sendMessage(payload, (response) => {
        const lastError = chrome.runtime.lastError;
        if (lastError?.message) {
          finish(() => reject(new Error(lastError.message)));
          return;
        }
        finish(() => resolve(response as T));
      });
    } catch (err) {
      finish(() => reject(err instanceof Error ? err : new Error(String(err))));
    }
  });
}

async function handleToolCall(entry: SessionWs, call: ToolCall): Promise<void> {
  log('tool_call:', call.tool, call.action_id, 'session:', call.session, call.quiet ? '(quiet)' : '');

  if (!call.quiet) {
    broadcastToolActivity(call, 'start');
  }

  let result: { ok: boolean; data?: unknown; error?: string };
  try {
    result = await sendRuntimeMessage<{ ok: boolean; data?: unknown; error?: string }>(
      {
        kind: 'execute_browser_tool',
        tool: call.tool,
        args: call.args ?? {},
        sessionName: call.session,
      } as ExecuteBrowserToolMsg,
      TOOL_EXECUTE_TIMEOUT_MS,
    );
  } catch (err) {
    result = { ok: false, error: String(err) };
  }

  if (!call.quiet) {
    broadcastToolActivity(call, 'done', result.ok, summarizeToolResult(result));
  }

  const payload: BrowserResult = {
    type: 'browser_result',
    action_id: call.action_id,
    ok: result.ok,
    data: result.data ?? null,
    error: result.error,
  };

  if (entry.ws?.readyState === WebSocket.OPEN) {
    entry.ws.send(JSON.stringify(payload));
    log('browser_result sent:', call.action_id, result.ok ? 'ok' : result.error);
  } else {
    log('browser_result dropped — WS not open for', call.session, '— bridge will 504');
  }
}

async function waitForWsOpen(sessionName: string, timeoutMs: number): Promise<void> {
  const entry = getOrCreateEntry(sessionName);
  if (entry.ws?.readyState === WebSocket.OPEN) return;

  let forcedReconnects = 0;
  await new Promise<void>((resolve, reject) => {
    let deadline = Date.now() + timeoutMs;
    const tick = async (): Promise<void> => {
      if (entry.ws?.readyState === WebSocket.OPEN) {
        resolve();
        return;
      }
      const stuckMs =
        entry.ws?.readyState === WebSocket.CONNECTING && entry.connectStartedAt
          ? Date.now() - entry.connectStartedAt
          : 0;
      const noSocket = !entry.ws || entry.ws.readyState === WebSocket.CLOSED;
      const shouldReset =
        forcedReconnects < 2 &&
        (noSocket || stuckMs >= CONNECTING_STUCK_MS);
      if (shouldReset) {
        forcedReconnects += 1;
        const token = await getToken();
        if (!token) {
          reject(new Error(`WS did not open for ${sessionName} — bridge token missing`));
          return;
        }
        resetSessionConnection(sessionName, token);
        deadline = Math.max(deadline, Date.now() + 12_000);
        setTimeout(() => void tick(), 50);
        return;
      }
      if (Date.now() >= deadline) {
        reject(new Error(`WS did not open for ${sessionName} within ${timeoutMs}ms`));
        return;
      }
      setTimeout(() => void tick(), 50);
    };
    void tick();
  });
}

function notifySendFailed(sessionName: string, reason: string): void {
  const msg: BridgeFrameMsg = {
    kind: 'bridge_frame',
    sessionName,
    frame: { type: 'ai_error', session: sessionName, exit_code: -1, stderr_tail: reason },
  };
  chrome.runtime.sendMessage(msg).catch(() => {});
}

// ─── Send dedupe (defense-in-depth against double-delivered send_to_bridge) ──
// A frame delivered twice (e.g. a broadcast echoed by another extension
// context — the old SW relay bug) arrives within milliseconds; a deliberate
// user retry comes seconds later. Window is short so retries never get eaten.
const SEND_DEDUPE_WINDOW_MS = 5_000;
const recentSendIds = new Map<string, number>();

/** Stable identity of an outbound frame, or null when it has none. */
function outboundFrameId(sessionName: string, frame: BridgeOutbound): string | null {
  if (frame.type === 'user_msg' && frame.client_msg_id) {
    return `${sessionName}:user_msg:${frame.client_msg_id}`;
  }
  if (frame.type === 'permission_response') {
    return `${sessionName}:perm:${frame.request_id}:${frame.option_id}`;
  }
  return null;
}

function isDuplicateSend(sessionName: string, frame: BridgeOutbound): boolean {
  const id = outboundFrameId(sessionName, frame);
  if (!id) return false;
  const now = Date.now();
  for (const [key, ts] of recentSendIds) {
    if (now - ts > SEND_DEDUPE_WINDOW_MS) recentSendIds.delete(key);
  }
  if (recentSendIds.has(id)) return true;
  recentSendIds.set(id, now);
  return false;
}

async function deliverFrame(sessionName: string, frame: BridgeOutbound): Promise<void> {
  log('deliver:', sessionName, frame.type);
  if (isDuplicateSend(sessionName, frame)) {
    log('deliver skipped — duplicate frame within dedupe window:', sessionName, frame.type);
    return;
  }
  keepOpenSessions.add(sessionName);
  await ensureSessionWs(sessionName, true);
  try {
    await waitForWsOpen(sessionName, WS_OPEN_TIMEOUT_MS);
  } catch (err) {
    // Still queue — pending frames flush when the socket reconnects.
    log('deliver: WS not ready yet, queueing frame:', sessionName, String(err));
  }
  touchSessionActivity(sessionName);
  sendFrame(sessionName, frame);
}

function sendFrame(sessionName: string, frame: BridgeOutbound): void {
  const entry = getOrCreateEntry(sessionName);
  touchSessionActivity(sessionName);
  if (entry.ws?.readyState === WebSocket.OPEN) {
    log('send:', sessionName, frame);
    entry.ws.send(JSON.stringify(frame));
  } else {
    log('queue:', sessionName, '(WS state:', entry.ws?.readyState ?? 'no ws', ')');
    entry.pending.push(frame);
  }
}

async function ensureSessionWs(sessionName: string, _force = false): Promise<void> {
  // Explicit ensure from the panel always means "this session must stay up".
  // Without this, a lost keepOpen set (offscreen restart / bad idle sweep)
  // permanently skipped connect while HTTP still looked healthy.
  keepOpenSessions.add(sessionName);
  const entry = sessions.get(sessionName);
  if (entry?.ws?.readyState === WebSocket.OPEN) {
    sendHello(entry.ws);
    notifyStatus(sessionName, true);
    return;
  }
  // Clear closed latch from a prior closeSessionWs so reconnect can proceed.
  if (entry?.closed) {
    entry.closed = false;
  }
  const token = await getToken();
  connect(sessionName, token);
}

function closeSessionWs(sessionName: string): void {
  const entry = sessions.get(sessionName);
  if (!entry) return;
  entry.closed = true;
  if (entry.reconnectTimer !== null) {
    clearTimeout(entry.reconnectTimer);
    entry.reconnectTimer = null;
  }
  entry.ws?.close();
  sessions.delete(sessionName);
}

// ─── Message listener ─────────────────────────────────────────────────────────

// ─── Eager session bootstrap ──────────────────────────────────────────────────
// Don't wait for side-panel messages. As soon as we load, fetch the session
// list from the bridge and open a WS for each one. Refresh every 15s to pick
// up new sessions and tear down deleted ones.

async function bootstrapSessions(overrideToken?: string): Promise<void> {
  const token = overrideToken ?? await getToken();
  if (!token) {
    log('bootstrap skipped — no token in storage');
    return;
  }
  try {
    const res = await fetch(`${BRIDGE_BASE_HTTP}/sessions`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) {
      log('bootstrap fetch failed:', res.status);
      return;
    }
    const body = (await res.json()) as { sessions: Record<string, unknown> };
    const names = Object.keys(body.sessions);
    log('bootstrap: bridge has', names.length, 'sessions');
    for (const name of names) {
      if (shouldBootstrapConnect(name)) {
        connect(name, token);
      }
    }
    for (const name of [...sessions.keys()]) {
      if (shouldStayConnected(name)) {
        connect(name, token);
      } else {
        closeSessionWs(name);
      }
    }
  } catch (err) {
    log('bootstrap error:', err);
  }
}

function resetAllSessions(): void {
  for (const entry of sessions.values()) {
    closeWsEntry(entry);
    entry.backoffMs = BACKOFF_INITIAL_MS;
    entry.closed = false;
    entry.pending = [];
  }
  sessions.clear();
  keepOpenSessions.clear();
}

function signalReady(): void {
  chrome.runtime.sendMessage({ kind: 'offscreen_ready' }).catch(() => {});
}

function handleInboundMessage(msg: unknown): void {
  const m = msg as
    | SendToBridgeMsg
    | UpdateTokenMsg
    | SetTokenMsg
    | SetProfileMsg
    | EnsureSessionWsMsg
    | SyncWsKeepaliveMsg
    | ResetSessionWsMsg
    | CloseSessionWsMsg
    | RecorderStartMsg
    | RecorderStopMsg
    | { kind: 'speech_stt_start'; lang?: string }
    | { kind: 'speech_stt_stop' };
  log('recv message:', m.kind, 'kind' in m ? (m as { sessionName?: string }).sessionName ?? '' : '');

  if (m.kind === 'set_token') {
    const hadToken = Boolean(cachedToken);
    setCachedToken(m.token);
    // First time we learn the token: open sockets for any known/bridge sessions.
    if (!hadToken && m.token) {
      bootstrapSessions(m.token).catch((err) => log('bootstrap after set_token error:', err));
    }
    return;
  }

  if (m.kind === 'set_profile') {
    cachedProfileId = m.profileId;
    cachedProfileLabel = m.profileLabel;
    log('profile set:', m.profileLabel, m.profileId);
    broadcastHello();  // announce to any already-open sockets
    return;
  }

  if (m.kind === 'send_to_bridge') {
    deliverFrame(m.sessionName, m.frame).catch((err) => {
      log('deliverFrame error:', err);
      notifySendFailed(m.sessionName, String(err));
    });
    return;
  }

  if (m.kind === 'ensure_session_ws') {
    ensureSessionWs(m.sessionName).catch((err) => log('ensureSessionWs error:', err));
    return;
  }

  if (m.kind === 'sync_ws_keepalive') {
    applyWsKeepalive(m.keepOpen ?? []);
    return;
  }

  if (m.kind === 'reset_session_ws') {
    getToken()
      .then((token) => resetSessionConnection(m.sessionName, token))
      .catch((err) => log('reset_session_ws error:', err));
    return;
  }

  if (m.kind === 'close_session_ws') {
    closeSessionWs(m.sessionName);
    return;
  }

  // ─── Recording ───────────────────────────────────────────────────────────
  if (m.kind === 'recorder_start') {
    getToken()
      .then((token) => startRecording(m.streamId, token))
      .catch((err) => log('startRecording error:', err));
    return;
  }

  if (m.kind === 'recorder_stop') {
    stopRecording();
    return;
  }

  if (m.kind === 'speech_stt_start') {
    const lang = (m as { lang?: string }).lang ?? 'en-US';
    startSpeechRecognition(lang);
    return;
  }

  if (m.kind === 'speech_stt_stop') {
    stopSpeechRecognition();
    return;
  }

  if (m.kind === 'play_action_sound') {
    try {
      const ctx = new AudioContext();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.frequency.value = 880;
      gain.gain.value = 0.04;
      osc.start();
      osc.stop(ctx.currentTime + 0.08);
      setTimeout(() => void ctx.close(), 200);
    } catch {
      /* audio unavailable */
    }
    return;
  }

  if (m.kind === 'update_token') {
    log('token updated — re-bootstrapping sessions');
    setCachedToken(m.token);
    resetAllSessions();
    bootstrapSessions(m.token)
      .then(signalReady)
      .catch((err) => log('bootstrap after token update error:', err));
  }
}

const INBOUND_KINDS = new Set([
  'send_to_bridge',
  'update_token',
  'set_token',
  'set_profile',
  'ensure_session_ws',
  'sync_ws_keepalive',
  'reset_session_ws',
  'close_session_ws',
  'recorder_start',
  'recorder_stop',
  'speech_stt_start',
  'speech_stt_stop',
  'play_action_sound',
]);

chrome.runtime.onMessage.addListener((msg: unknown) => {
  const kind = (msg as { kind?: string }).kind;
  if (!kind || !INBOUND_KINDS.has(kind)) return;

  handleInboundMessage(msg);
});

// `chrome.storage` is not guaranteed to be exposed to offscreen documents, so
// guard this listener — the token is also pushed via `update_token`/`wake_offscreen`.
chrome.storage?.onChanged?.addListener((changes, area) => {
  if (area !== 'local' || !changes[STORAGE_TOKEN_KEY]) return;
  const next = changes[STORAGE_TOKEN_KEY].newValue as string | undefined;
  log('storage token changed');
  setCachedToken(next ?? '');
  resetAllSessions();
  if (next) {
    bootstrapSessions(next)
      .then(signalReady)
      .catch((err) => log('bootstrap after storage change error:', err));
  }
});

bootstrapSessions()
  .then(signalReady)
  .catch((err) => log('bootstrap top-level error:', err));
setInterval(() => bootstrapSessions().catch(() => {}), SESSIONS_POLL_MS);
setInterval(() => sweepIdleUserSessions(), IDLE_SWEEP_MS);

// MV3 service workers idle-kill workaround (same pattern as Claude in Chrome offscreen).
setInterval(() => {
  chrome.runtime.sendMessage({ kind: 'sw_keepalive' }).catch(() => {});
}, 20_000);

log('offscreen loaded, listener registered');
