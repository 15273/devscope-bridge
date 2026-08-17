/**
 * messaging.ts — chrome.runtime message envelopes between
 * side panel ↔ service worker ↔ offscreen document.
 */
import type { BridgeInbound, BridgeOutbound } from './frames';

/** Side panel → offscreen: send a frame to the bridge on a specific session WS. */
export interface SendToBridgeMsg {
  kind: 'send_to_bridge';
  sessionName: string;
  frame: BridgeOutbound;
}

/** Offscreen → side panel: a frame arrived from the bridge for a session. */
export interface BridgeFrameMsg {
  kind: 'bridge_frame';
  sessionName: string;
  frame: BridgeInbound;
}

/** Side panel → service worker: request connection status for a session. */
export interface GetStatusMsg {
  kind: 'get_status';
  sessionName: string;
}

/** Service worker → side panel: current connection status for a session. */
export interface StatusMsg {
  kind: 'status';
  sessionName: string;
  connected: boolean;
}

/** Side panel → service worker: update token and reconnect all sessions. */
export interface UpdateTokenMsg {
  kind: 'update_token';
  token: string;
}

/**
 * Service worker → offscreen: cache the bridge token WITHOUT reconnecting.
 *
 * The offscreen document cannot read `chrome.storage`, so the service worker
 * (which can) pushes the token down after the document is ready. Unlike
 * `update_token`, this does not tear down/reconnect existing session sockets.
 */
export interface SetTokenMsg {
  kind: 'set_token';
  token: string;
}

/**
 * Service worker → offscreen: announce which Chrome profile this extension
 * instance runs in. The offscreen layer includes it in the WS `hello` frame so
 * the bridge can list tabs across profiles and route actions to the right one.
 */
export interface SetProfileMsg {
  kind: 'set_profile';
  profileId: string;
  profileLabel: string;
}

/** Side panel → offscreen: ensure a WS is open for a session. */
export interface EnsureSessionWsMsg {
  kind: 'ensure_session_ws';
  sessionName: string;
}

/** Side panel → offscreen: force-close and reopen WS (Reconnect button). */
export interface ResetSessionWsMsg {
  kind: 'reset_session_ws';
  sessionName: string;
}

/** Side panel → offscreen: close WS for a deleted session. */
export interface CloseSessionWsMsg {
  kind: 'close_session_ws';
  sessionName: string;
}

/** Side panel → offscreen: which sessions should keep WS open; others are torn down. */
export interface SyncWsKeepaliveMsg {
  kind: 'sync_ws_keepalive';
  keepOpen: string[];
}

/** Offscreen → service worker: reset MV3 idle timer (pattern from Claude in Chrome). */
export interface SwKeepaliveMsg {
  kind: 'sw_keepalive';
}

/**
 * Side panel → service worker: ensure offscreen document is alive.
 *
 * Optionally carries the bridge token. The service worker forwards it to the
 * offscreen document, which cannot read `chrome.storage` itself. The side panel
 * may omit it (the service worker will read it from storage as a fallback).
 */
export interface WakeOffscreenMsg {
  kind: 'wake_offscreen';
  token?: string;
}

/** Offscreen → service worker: offscreen script loaded and listening. */
export interface OffscreenReadyMsg {
  kind: 'offscreen_ready';
}

/** Offscreen → service worker: run a browser-control MCP tool. */
export interface ExecuteBrowserToolMsg {
  kind: 'execute_browser_tool';
  tool: string;
  args: Record<string, unknown>;
  sessionName?: string;
}

/** Side panel → service worker: register which browser window hosts the panel. */
export interface RegisterPanelHostMsg {
  kind: 'register_panel_host';
  windowId: number;
}

/** Side panel → service worker: read stable Chrome profile identity. */
export interface GetProfileIdentityMsg {
  kind: 'get_profile_identity';
}

export interface ProfileIdentityResponse {
  ok: boolean;
  profileId?: string;
  profileLabel?: string;
  error?: string;
}

/** Side panel → service worker: list scriptable tabs for picker. */
export interface ListBrowserTabsMsg {
  kind: 'list_browser_tabs';
}

export interface ListBrowserTabsResponse {
  ok: boolean;
  tabs?: import('./tabBinding').BrowserTabSummary[];
}

/**
 * Offscreen → side panel: the agent invoked a browser tool on this session.
 * Emitted on `start` (when the tool_call arrives) and `done` (with the result)
 * so the chat can render a transparent, collapsible tool-call log.
 */
export interface ToolActivityMsg {
  kind: 'tool_activity';
  sessionName: string;
  actionId: string;
  tool: string;
  phase: 'start' | 'done';
  ok?: boolean;
  summary?: string;
}

// ─── Recording messages ───────────────────────────────────────────────────────

/**
 * Side panel → service worker: begin recording the active tab.
 * The service worker calls chrome.tabCapture.getMediaStreamId, then forwards
 * a recorder_start message to the offscreen document.
 */
export interface StartRecordingMsg {
  kind: 'start_recording';
  /** Optional — resolved in side panel when present (preserves user gesture). */
  tabId?: number;
}

/**
 * Side panel → service worker: stop an in-progress recording.
 * The service worker forwards a recorder_stop message to offscreen.
 */
export interface StopRecordingMsg {
  kind: 'stop_recording';
}

/**
 * Service worker → offscreen: begin tab capture with the given stream id.
 * streamId comes from chrome.tabCapture.getMediaStreamId and expires quickly —
 * the offscreen document must call getUserMedia immediately.
 */
export interface RecorderStartMsg {
  kind: 'recorder_start';
  streamId: string;
}

/**
 * Service worker → offscreen: stop the current MediaRecorder and flush the
 * recorded webm blob to disk via chrome.downloads.
 */
export interface RecorderStopMsg {
  kind: 'recorder_stop';
}

/**
 * Offscreen → all listeners (broadcast): recording state changed.
 * The side panel listens to this to update the record button and show the
 * elapsed-time indicator.
 *
 * - recording: true  → capture is live
 * - recording: false → capture ended (or never started)
 * - error: present   → something went wrong (restricted tab, permission denied, …)
 */
export interface RecordingStatusMsg {
  kind: 'recording_status';
  recording: boolean;
  error?: string;
}

/** Side panel → offscreen: start speech-to-text in the offscreen document. */
export interface SpeechSttStartMsg {
  kind: 'speech_stt_start';
  lang: string;
}

/** Side panel → offscreen: stop speech-to-text. */
export interface SpeechSttStopMsg {
  kind: 'speech_stt_stop';
}

/** Offscreen → side panel: transcript chunk or status change. */
export interface SpeechSttEventMsg {
  kind: 'speech_stt_event';
  phase: 'transcript' | 'status';
  text?: string;
  status?: 'idle' | 'listening' | 'unsupported' | 'denied' | 'error';
  error?: string;
}

export type ExtensionMsg =
  | SendToBridgeMsg
  | BridgeFrameMsg
  | GetStatusMsg
  | StatusMsg
  | UpdateTokenMsg
  | SetTokenMsg
  | SetProfileMsg
  | EnsureSessionWsMsg
  | CloseSessionWsMsg
  | WakeOffscreenMsg
  | OffscreenReadyMsg
  | SwKeepaliveMsg
  | ExecuteBrowserToolMsg
  | ToolActivityMsg
  | StartRecordingMsg
  | StopRecordingMsg
  | RecorderStartMsg
  | RecorderStopMsg
  | RecordingStatusMsg
  | SpeechSttStartMsg
  | SpeechSttStopMsg
  | SpeechSttEventMsg
  | RegisterPanelHostMsg
  | GetProfileIdentityMsg
  | ListBrowserTabsMsg;
