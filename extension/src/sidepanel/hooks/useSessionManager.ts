/**
 * useSessionManager — central hook for multi-session state.
 *
 * - Polls GET /sessions on mount and every 30s.
 * - Subscribes to chrome.runtime.onMessage for WS frames.
 * - Persists chat history to chrome.storage.local (per-profile cache) on every update.
 * - On load, merges with the bridge JSONL transcript so chats sync across Chrome profiles.
 * - Exposes actions: switchSession, sendMessage, createSession, deleteSession.
 */
import { useEffect, useReducer, useCallback, useRef, type RefObject } from 'react';
import type { BridgeFrameMsg, StatusMsg, ToolActivityMsg } from '@/shared/messaging';
import type { SessionInfo, CreateSessionPayload, MessageContext, AgentMode, UserMsg } from '@/shared/frames';
import { storeReducer, INITIAL_STATE, sessionLooksStuckWorking } from '../store/sessionStore';
import { saveHistory, clearHistory, loadCoachPrefs, loadContextPrefs } from '../utils/storage';
import { loadSessionHistory, messagesToBridgeTurns } from '../utils/historyLoader';
import {
  needsTranscriptBackfill,
  hasEmptyStreamingAssistant,
  isSessionWorking,
  transcriptAheadOfUi,
} from '../utils/transcriptSync';
import { isSessionControlCommand, sessionControlHint } from '../utils/sessionControlCommands';
import { classifyCompactActivity, isSteeringDropWarning } from '../utils/bridgeFrameHints';
import { autoBindTabFromText, bindTabById, tryAutoBindIfEmpty } from '../utils/autoBindTab';
import { enrichContextWithBoundTab } from '@/shared/messageContext';
import { loadBoundTab } from '@/shared/tabBinding';
import type { TerminalViewHandle } from '../components/TerminalView';
import { formatPtyUserTurn, persistOutboxAttachments } from '../utils/ptyUserMessage';
import {
  BRIDGE_HTTP,
  authHeaders,
  bridgeFetch,
  getToken,
  interruptSession,
  resetSessionBridge,
  fetchTranscript,
  fetchPendingRequests,
  requestSessionCompact,
  syncBridgeHistory,
} from '../bridge';
import { collectWsKeepOpen } from '@/shared/wsKeepalive';
import { streamDebug } from '../utils/streamDebug';
import { createHistoryPersister, type HistoryPersister } from '../utils/historyPersist';

const SESSION_POLL_IDLE_MS = 15_000;
const SESSION_POLL_ACTIVE_MS = 2_500;
/** Pull JSONL for the *active* chat only while a turn looks stuck (missed WS). */
const LIVE_BACKFILL_MS = 2_000;
/** Roll back an optimistic send when no msg_ack/perm_ack arrived in time (C3). */
const ACK_TIMEOUT_MS = 8_000;
/** Port name the service worker uses to know the panel is open (C4 badge). */
const PANEL_PORT_NAME = 'devscope-panel';

async function fetchSessions(token: string): Promise<Record<string, SessionInfo>> {
  const res = await bridgeFetch(`${BRIDGE_HTTP}/sessions`, { headers: authHeaders(token) });
  if (!res.ok) throw new Error(`GET /sessions failed: ${res.status}`);
  const body = await res.json() as { sessions: Record<string, SessionInfo> };
  return body.sessions;
}

async function wakeOffscreen(): Promise<void> {
  // Push the token along with the wake: the offscreen document cannot read
  // `chrome.storage` itself, so it relies on the token being handed to it.
  const token = await getToken().catch(() => '');
  const resp = await chrome.runtime.sendMessage({ kind: 'wake_offscreen', token }) as { ok?: boolean; error?: string };
  if (!resp?.ok) {
    console.warn('[DevScope] offscreen wake failed:', resp?.error ?? 'unknown');
  }
}

async function ensureSessionWsReady(sessionName: string): Promise<void> {
  const resp = (await chrome.runtime.sendMessage({
    kind: 'ensure_session_ws',
    sessionName,
  })) as { ok?: boolean; error?: string };
  if (!resp?.ok) {
    throw new Error(resp?.error ?? 'ensure_session_ws failed');
  }
}

async function syncWsKeepalive(keepOpen: string[]): Promise<void> {
  await wakeOffscreen().catch(() => {});
  const resp = (await chrome.runtime.sendMessage({
    kind: 'sync_ws_keepalive',
    keepOpen,
  })) as { ok?: boolean; error?: string };
  if (!resp?.ok) {
    console.warn('[DevScope] sync_ws_keepalive failed:', resp?.error ?? 'unknown');
    return;
  }
  await Promise.all(keepOpen.map((name) => ensureSessionWsReady(name).catch(() => {})));
}

export function useSessionManager() {
  const [state, dispatch] = useReducer(storeReducer, INITIAL_STATE);
  const stateRef = useRef(state);
  stateRef.current = state;
  const prevTurnRunningRef = useRef<Record<string, boolean>>({});
  /** Consecutive polls where HTTP works but active session WS is down. */
  const wsHealMissesRef = useRef(0);
  const historyLoadInFlightRef = useRef<Set<string>>(new Set());
  const syncTranscriptRef = useRef<(name: string, force?: boolean) => Promise<void>>(async () => {});
  const mergeTranscriptRef = useRef<(name: string) => Promise<void>>(async () => {});
  const terminalModeSessionRef = useRef<string | null>(null);
  /** Prevent parallel /transcript storms for the same session. */
  const transcriptInflightRef = useRef<Set<string>>(new Set());
  const recoverPendingRef = useRef<(name: string) => Promise<void>>(async () => {});
  /** Sessions whose pending interactive requests were already recovered (C4). */
  const recoveredPendingRef = useRef(new Set<string>());
  /** client_msg_id → rollback timer for unacked user messages (C3). */
  const msgAckTimersRef = useRef(new Map<string, ReturnType<typeof setTimeout>>());
  /** request_id → in-flight permission decision awaiting perm_ack (C3). */
  const permPendingRef = useRef(
    new Map<string, { session: string; optionId: string; timer: ReturnType<typeof setTimeout> }>(),
  );
  /** Flips true on the first ack — bridges without contract-1 support never roll back. */
  const ackCapableRef = useRef(false);
  /** client_msg_id → original frame, kept until acked so Retry can resend it. */
  const sentFramesRef = useRef(new Map<string, UserMsg>());

  const setTerminalModeSession = useCallback((name: string | null) => {
    terminalModeSessionRef.current = name;
  }, []);

  /** Bridge HTTP reachability — drives the connection banner (C2). */
  const setBridgeUnreachable = useCallback((value: boolean) => {
    if (stateRef.current.bridgeUnreachable !== value) {
      dispatch({ type: 'SET_BRIDGE_UNREACHABLE', value });
    }
  }, []);

  const syncTranscript = useCallback(async (name: string, force = false): Promise<void> => {
    if (transcriptInflightRef.current.has(name)) return;
    transcriptInflightRef.current.add(name);
    try {
      const result = await fetchTranscript(name);
      if (!result.ok) {
        // Bridge failure ≠ empty transcript — surface it, never silently skip (C2).
        streamDebug('warn', name, 'syncTranscript bridge unreachable', { force });
        setBridgeUnreachable(true);
        return;
      }
      setBridgeUnreachable(false);
      const turns = result.turns;
      if (turns.length === 0) {
        streamDebug('sync', name, 'fetch empty', { force });
        return;
      }
      streamDebug('sync', name, force ? 'LOAD force' : 'LOAD', {
        turns: turns.length,
        lastRole: turns[turns.length - 1]?.role,
        lastLen: turns[turns.length - 1]?.text?.length ?? 0,
      });
      dispatch({ type: 'LOAD_TRANSCRIPT', session: name, turns, force });
    } catch (err) {
      streamDebug('warn', name, 'syncTranscript failed', { err: String(err) });
      console.warn('[DevScope] syncTranscript failed:', err);
    } finally {
      transcriptInflightRef.current.delete(name);
    }
  }, [setBridgeUnreachable]);

  const mergeTranscript = useCallback(async (name: string): Promise<void> => {
    if (terminalModeSessionRef.current === name) {
      streamDebug('merge', name, 'skipped (terminal mode)');
      return;
    }
    if (transcriptInflightRef.current.has(name)) return;
    transcriptInflightRef.current.add(name);
    try {
      const sessionBefore = stateRef.current.sessions[name];
      if (!sessionBefore || sessionBefore.isLoadingHistory) return;
      const result = await fetchTranscript(name);
      if (!result.ok) {
        streamDebug('warn', name, 'mergeTranscript bridge unreachable');
        setBridgeUnreachable(true);
        return;
      }
      setBridgeUnreachable(false);
      const turns = result.turns;
      if (turns.length === 0) {
        streamDebug('merge', name, 'fetch empty');
        return;
      }
      // Re-read after await — SET_SESSIONS / CHUNK may have landed mid-fetch.
      const session = stateRef.current.sessions[name] ?? sessionBefore;
      if (session.isLoadingHistory) return;
      if (!transcriptAheadOfUi(session, turns)) {
        // Empty spinner + idle bridge: force full reload (same recovery as closing terminal).
        if (hasEmptyStreamingAssistant(session) && session.turnRunning !== true) {
          streamDebug('merge', name, 'not ahead → force LOAD (empty idle spinner)', {
            turns: turns.length,
          });
          dispatch({ type: 'LOAD_TRANSCRIPT', session: name, turns, force: true });
        } else {
          streamDebug('merge', name, 'not ahead (no-op)', {
            emptyStream: hasEmptyStreamingAssistant(session),
            turnRunning: session.turnRunning,
            turns: turns.length,
          });
        }
        return;
      }
      streamDebug('merge', name, 'MERGE_TRANSCRIPT', {
        turns: turns.length,
        keepStreaming: Boolean(session.turnRunning),
      });
      dispatch({ type: 'MERGE_TRANSCRIPT', session: name, turns });
    } catch (err) {
      streamDebug('warn', name, 'mergeTranscript failed', { err: String(err) });
      console.warn('[DevScope] mergeTranscript failed:', err);
    } finally {
      transcriptInflightRef.current.delete(name);
    }
  }, [setBridgeUnreachable]);

  /** Re-render unresolved approval/question cards from the bridge (contract 3). */
  const recoverPending = useCallback(async (name: string): Promise<void> => {
    const pending = await fetchPendingRequests(name);
    for (const req of pending) {
      dispatch({
        type: 'PERMISSION_REQUEST',
        session: name,
        requestId: req.request_id,
        kind: req.kind,
        title: req.title,
        description: req.description,
        options: req.options,
        questions: req.questions ?? undefined,
        toolName: req.tool_name ?? undefined,
      });
    }
  }, []);

  /**
   * POST /compact with a visible lifecycle card (C8). The card opens
   * immediately; the bridge's own compact frames (or the response) close it.
   */
  const compactSession = useCallback((sessionName: string, startDetail?: string) => {
    dispatch({ type: 'COMPACT_STATE', session: sessionName, phase: 'start', detail: startDetail });
    requestSessionCompact(sessionName)
      .then((compact) => {
        dispatch({
          type: 'COMPACT_STATE',
          session: sessionName,
          phase: 'done',
          detail: compact.was_real_summary
            ? 'Summary saved — the next message includes it.'
            : 'Fallback recovery note saved.',
        });
      })
      .catch((err) => {
        dispatch({
          type: 'COMPACT_STATE',
          session: sessionName,
          phase: 'failed',
          detail: err instanceof Error ? err.message : String(err),
        });
      });
  }, []);

  syncTranscriptRef.current = syncTranscript;
  mergeTranscriptRef.current = mergeTranscript;
  recoverPendingRef.current = recoverPending;

  /** Sessions that should reload from the bridge JSONL transcript. */
  const collectTranscriptSyncTargets = useCallback(
    (infos: Record<string, SessionInfo>): string[] => {
      const prev = prevTurnRunningRef.current;
      const targets = new Set<string>();

      for (const [name, info] of Object.entries(infos)) {
        const wasRunning = prev[name] ?? false;
        const nowRunning = info.turn_running ?? false;
        prev[name] = nowRunning;

        if (nowRunning) continue;

        if (wasRunning) {
          targets.add(name);
          continue;
        }

        const session = stateRef.current.sessions[name];
        // Bridge already reports this session idle (nowRunning === false). If the UI
        // is behind — including when a stale tool row keeps it "working" — reload it.
        if (session && needsTranscriptBackfill(session)) {
          targets.add(name);
        }
      }

      return [...targets];
    },
    [],
  );

  // ─── Load sessions from bridge ──────────────────────────────────────────

  const refreshSessions = useCallback(async () => {
    try {
      const token = await getToken();
      const infos = await fetchSessions(token);
      setBridgeUnreachable(false);
      // First sight of a session → recover pending interactive requests (C4).
      for (const name of Object.keys(infos)) {
        if (!recoveredPendingRef.current.has(name)) {
          recoveredPendingRef.current.add(name);
          recoverPendingRef.current(name).catch(() => {});
        }
      }
      const syncTargets = new Set(collectTranscriptSyncTargets(infos));
      const activeName = stateRef.current.activeSession;
      // Only force-reload the active chat's empty spinner — never fan out to
      // every orchestrator worker (mgr-research JSONL is tens of MB and starves WS).
      if (activeName) {
        const session = stateRef.current.sessions[activeName];
        const bridgeRunning = infos[activeName]?.turn_running === true;
        if (session && !bridgeRunning && hasEmptyStreamingAssistant(session)) {
          syncTargets.add(activeName);
        }
      }
      // Drop sync targets that are not the active chat (except just-finished turns
      // already collected for the active session by collectTranscriptSyncTargets).
      for (const name of [...syncTargets]) {
        if (name !== activeName) syncTargets.delete(name);
      }
      dispatch({ type: 'SET_SESSIONS', infos });
      streamDebug('poll', '*', 'GET /sessions', {
        count: Object.keys(infos).length,
        syncTargets: [...syncTargets],
        running: Object.entries(infos)
          .filter(([, i]) => i.turn_running)
          .map(([n]) => n),
      });
      // Soft-merge ONLY the active session — mass /transcript polls starve the bridge.
      if (activeName && infos[activeName]) {
        mergeTranscriptRef.current(activeName).catch(() => {});
        const after = stateRef.current.sessions[activeName];
        // Bridge idle but panel still shows Thinking/tools-running for an hour —
        // force-clear (persist: chrome.storage can rehydrate orphan tool rows).
        if (
          after &&
          infos[activeName].turn_running !== true &&
          sessionLooksStuckWorking({ ...after, turnRunning: false })
        ) {
          streamDebug('ui', activeName, 'FORCE_TURN_IDLE (bridge idle, UI stuck)');
          dispatch({ type: 'FORCE_TURN_IDLE', session: activeName });
          dispatch({ type: 'SET_RECONNECTING', value: false });
        }
      }
      for (const name of syncTargets) {
        syncTranscriptRef.current(name, true).catch(() => {});
      }
      const keepOpen = collectWsKeepOpen(stateRef.current.activeSession, stateRef.current.sessions);
      syncWsKeepalive(keepOpen).catch(() => {});
      if (activeName) {
        const sess = stateRef.current.sessions[activeName];
        if (sess && !sess.isConnected) {
          wsHealMissesRef.current += 1;
          // HTTP /sessions succeeded above — bridge is up. Force WS heal after
          // two consecutive misses so "Reconnecting…" cannot stick for an hour.
          if (wsHealMissesRef.current >= 2) {
            wsHealMissesRef.current = 0;
            streamDebug('ui', activeName, 'WS heal: HTTP ok, forcing reset_session_ws');
            chrome.runtime
              .sendMessage({ kind: 'reset_session_ws', sessionName: activeName })
              .then(() => ensureSessionWsReady(activeName))
              .catch(() => {});
          } else {
            ensureSessionWsReady(activeName).catch(() => {});
          }
        } else {
          wsHealMissesRef.current = 0;
          ensureSessionWsReady(activeName).catch(() => {});
        }
      }
    } catch {
      // Bridge unreachable (down, hung, or bad token) — show the banner.
      setBridgeUnreachable(true);
    }
  }, [collectTranscriptSyncTargets, setBridgeUnreachable]);

  useEffect(() => {
    wakeOffscreen().catch(() => {});
    void chrome.windows.getCurrent().then((win) => {
      if (win.id != null) {
        chrome.runtime.sendMessage({ kind: 'register_panel_host', windowId: win.id }).catch(() => {});
      }
    });
    refreshSessions();
    let timer: ReturnType<typeof setTimeout>;
    let stopped = false;
    const schedule = () => {
      if (stopped) return;
      const active = stateRef.current.activeSession;
      const s = active ? stateRef.current.sessions[active] : undefined;
      const anyWorking = Boolean(
        s &&
          (s.turnRunning ||
            Boolean(s.turnStartedAt) ||
            hasEmptyStreamingAssistant(s) ||
            s.messages.some((m) => m.role === 'assistant' && m.isStreaming)),
      );
      timer = setTimeout(async () => {
        // try/finally: the loop must re-arm no matter how refresh fails (C2).
        try {
          await refreshSessions();
        } finally {
          schedule();
        }
      }, anyWorking ? SESSION_POLL_ACTIVE_MS : SESSION_POLL_IDLE_MS);
    };
    schedule();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [refreshSessions]);

  // Long-lived port so the service worker knows the panel is open (clears the
  // attention badge; permission notifications only fire while disconnected).
  useEffect(() => {
    try {
      const port = chrome.runtime.connect({ name: PANEL_PORT_NAME });
      return () => port.disconnect();
    } catch {
      return undefined;
    }
  }, []);

  // Missed WS chunks: poll JSONL for the *active* chat only (never fan-out).
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    const tick = () => {
      const active = stateRef.current.activeSession;
      const session = active ? stateRef.current.sessions[active] : undefined;
      if (active && session && terminalModeSessionRef.current !== active) {
        // Orphan Thinking for >45s with bridge idle → force clear (1h+ ghost turns).
        const startedAgo = session.turnStartedAt
          ? Date.now() - session.turnStartedAt
          : 0;
        if (
          session.turnRunning !== true &&
          sessionLooksStuckWorking(session) &&
          (startedAgo > 45_000 || !session.turnStartedAt)
        ) {
          streamDebug('ui', active, 'FORCE_TURN_IDLE (stale sweeper)', {
            startedAgoMs: startedAgo,
          });
          dispatch({ type: 'FORCE_TURN_IDLE', session: active });
          dispatch({ type: 'SET_RECONNECTING', value: false });
        }
        const needy =
          hasEmptyStreamingAssistant(session) ||
          session.turnRunning === true;
        if (needy) {
          mergeTranscriptRef.current(active).catch(() => {});
          if (hasEmptyStreamingAssistant(session) && session.turnRunning !== true) {
            syncTranscriptRef.current(active, true).catch(() => {});
          }
        }
      }
      const stillNeedy = Boolean(
        active &&
          stateRef.current.sessions[active] &&
          (hasEmptyStreamingAssistant(stateRef.current.sessions[active]) ||
            stateRef.current.sessions[active].turnRunning ||
            sessionLooksStuckWorking(stateRef.current.sessions[active])),
      );
      timer = setTimeout(tick, stillNeedy ? LIVE_BACKFILL_MS : LIVE_BACKFILL_MS * 4);
    };
    timer = setTimeout(tick, LIVE_BACKFILL_MS);
    return () => clearTimeout(timer);
  }, []);

  // When the side panel regains focus, WS frames may have been missed — pull transcript tail.
  useEffect(() => {
    function onVisibilityChange() {
      if (document.visibilityState !== 'visible') return;
      const name = stateRef.current.activeSession;
      void chrome.windows.getCurrent().then((win) => {
        if (win.id != null) {
          chrome.runtime.sendMessage({ kind: 'register_panel_host', windowId: win.id }).catch(() => {});
        }
      });
      if (!name) return;
      mergeTranscriptRef.current(name).catch(() => {});
      recoverPendingRef.current(name).catch(() => {});
      const session = stateRef.current.sessions[name];
      if (session && (hasEmptyStreamingAssistant(session) || needsTranscriptBackfill(session))) {
        syncTranscriptRef.current(name, true).catch(() => {});
      }
    }
    document.addEventListener('visibilitychange', onVisibilityChange);
    return () => document.removeEventListener('visibilitychange', onVisibilityChange);
  }, []);

  const wsKeepKey = (() => {
    const keep = collectWsKeepOpen(state.activeSession, state.sessions);
    return keep.sort().join('|');
  })();

  // Keep WS open only for the active chat, running turns, and automation sessions.
  useEffect(() => {
    syncWsKeepalive(collectWsKeepOpen(state.activeSession, state.sessions)).catch(() => {});
  }, [wsKeepKey]);

  useEffect(() => {
    const name = state.activeSession;
    if (!name) return;
    loadBoundTab(name)
      .then(async (tab) => {
        dispatch({ type: 'SET_BOUND_TAB', session: name, tab });
        const prefs = await loadContextPrefs().catch(() => ({ autoBindFocusedTab: false, autoCompactEvery: 0 }));
        if (!tab && prefs.autoBindFocusedTab) {
          const bound = await tryAutoBindIfEmpty(name, true);
          if (bound) dispatch({ type: 'TAB_BOUND_ACK', session: name, tab: bound });
        }
      })
      .catch(() => {});
  }, [state.activeSession]);

  // ─── Load history when sessions appear ──────────────────────────────────

  useEffect(() => {
    for (const [name, session] of Object.entries(state.sessions)) {
      if (!session.isLoadingHistory) continue;
      if (historyLoadInFlightRef.current.has(name)) continue;
      historyLoadInFlightRef.current.add(name);
      const agent = session.agent;
      loadSessionHistory(name)
        .then((messages) => {
          dispatch({ type: 'SET_HISTORY', name, messages });
          if (agent === 'cursor') {
            void syncBridgeHistory(name, messagesToBridgeTurns(messages));
          }
        })
        .catch(() => {
          dispatch({ type: 'SET_HISTORY', name, messages: [] });
        })
        .finally(() => {
          historyLoadInFlightRef.current.delete(name);
        });
    }
  }, [state.sessions]);

  // ─── Persist history on change ───────────────────────────────────────────

  const persisterRef = useRef<HistoryPersister | null>(null);
  if (!persisterRef.current) {
    persisterRef.current = createHistoryPersister({
      save: (name, messages) => {
        saveHistory(name, messages).catch(() => {});
      },
      readMessages: (name) => stateRef.current.sessions[name]?.messages,
    });
  }
  useEffect(() => {
    persisterRef.current?.observe(state.sessions);
  }, [state.sessions]);
  useEffect(() => {
    const persister = persisterRef.current;
    return () => persister?.flush();
  }, []);

  // ─── chrome.runtime message listener ────────────────────────────────────

  useEffect(() => {
    function handleMessage(msg: unknown) {
      const m = msg as BridgeFrameMsg | StatusMsg | ToolActivityMsg;

      if (m.kind === 'status') {
        dispatch({ type: 'SESSION_STATUS', name: m.sessionName, connected: m.connected });
        streamDebug('ui', m.sessionName, m.connected ? 'WS connected' : 'WS disconnected', {
          reconnectAttempt: (m as { reconnectAttempt?: number }).reconnectAttempt,
        });
        if (m.connected) {
          dispatch({ type: 'SET_RECONNECTING', value: false });
        } else if ((m as { reconnectAttempt?: number }).reconnectAttempt) {
          dispatch({ type: 'SET_RECONNECTING', value: true });
        }
        return;
      }

      if (m.kind === 'tool_activity') {
        dispatch({
          type: 'TOOL_ACTIVITY',
          session: m.sessionName,
          actionId: m.actionId,
          tool: m.tool,
          phase: m.phase,
          ok: m.ok,
          summary: m.summary,
        });
        return;
      }

      if (m.kind === 'bridge_frame') {
        const { frame, sessionName } = m;
        streamDebug('ws_frame', sessionName, frame.type, {
          ...(frame.type === 'ai_chunk'
            ? { chars: typeof (frame as { text?: string }).text === 'string'
                ? (frame as { text: string }).text.length
                : 0 }
            : {}),
          ...(frame.type === 'turn_state'
            ? { running: (frame as { running?: boolean }).running }
            : {}),
          ...(frame.type === 'agent_activity'
            ? { label: (frame as { label?: string }).label }
            : {}),
        });
        switch (frame.type) {
          case 'ai_chunk': {
            // If the MEDIC is currently running, route this chunk to its card
            // rather than the normal assistant bubble.
            const isMedicRunning = stateRef.current.sessions[sessionName]?.medicRunning ?? false;
            if (isMedicRunning) {
              dispatch({ type: 'MEDIC_CHUNK', session: sessionName, text: frame.text });
            } else {
              dispatch({
                type: 'CHUNK',
                session: sessionName,
                text: frame.text,
                turnId: frame.turn_id ?? undefined,
                blockIndex: frame.block_index,
              });
            }
            break;
          }
          case 'thinking_chunk':
            dispatch({
              type: 'THINKING_CHUNK',
              session: sessionName,
              turnId: frame.turn_id ?? undefined,
              text: frame.text,
            });
            break;
          case 'turn_result':
            dispatch({
              type: 'TURN_RESULT',
              session: sessionName,
              turnId: frame.turn_id ?? undefined,
              meta: {
                durationMs: frame.duration_ms,
                costUsd: frame.cost_usd,
                inputTokens: frame.input_tokens,
                outputTokens: frame.output_tokens,
                model: frame.model,
              },
            });
            break;
          case 'ai_done':
            dispatch({ type: 'DONE', session: sessionName });
            // WS chunks may be dropped while the panel is idle; merge transcript tail
            // after each assistant segment (turn may still be running for tools / q2).
            queueMicrotask(() => {
              void (async () => {
                mergeTranscriptRef.current(sessionName).catch(() => {});
                // React may not have committed DONE yet — wait a tick then force if empty.
                await new Promise((r) => setTimeout(r, 50));
                const after = stateRef.current.sessions[sessionName];
                if (
                  after &&
                  (hasEmptyStreamingAssistant(after) || needsTranscriptBackfill(after))
                ) {
                  syncTranscriptRef.current(sessionName, true).catch(() => {});
                }
              })();
            });
            break;
          case 'ai_error':
            dispatch({
              type: 'ERROR',
              session: sessionName,
              text: `Error (exit ${frame.exit_code}): ${frame.stderr_tail}`,
            });
            break;
          case 'agent_activity': {
            // A tool-call lifecycle event (running/done/error, correlated by
            // call_id) → one permanent, in-place-updating tool row. Everything
            // else (call_id == null: Thinking…, ambient status) → activity strip.
            if (frame.call_id && frame.status) {
              dispatch({ type: 'TOOL_CALL', session: sessionName, activity: frame });
              break;
            }
            // A7 compact lifecycle → spinner card, not a plain activity label.
            const compactPhase = classifyCompactActivity(frame.label);
            if (compactPhase) {
              dispatch({
                type: 'COMPACT_STATE',
                session: sessionName,
                phase: compactPhase,
                detail: frame.detail ?? undefined,
              });
              break;
            }
            // A8 "steering may have been dropped" → warn on the queued bubble.
            if (isSteeringDropWarning(frame.label)) {
              dispatch({ type: 'STEERING_DROP_WARNING', session: sessionName });
              dispatch({ type: 'ACTIVITY', session: sessionName, label: frame.label });
              break;
            }
            const detail = frame.detail ?? undefined;
            const text = detail ? `${frame.label}: ${detail}` : frame.label;
            dispatch({ type: 'ACTIVITY', session: sessionName, label: text });
            break;
          }
          case 'usage':
            dispatch({
              type: 'USAGE',
              session: sessionName,
              tokens: frame.tokens,
              costUsd: frame.cost_usd,
              inputTokens: frame.input_tokens ?? 0,
            });
            break;
          case 'session_coach':
            dispatch({
              type: 'SESSION_COACH',
              session: sessionName,
              hint: {
                level: frame.level ?? 'warn',
                title: frame.title,
                body: frame.body ?? '',
                suggestedModel: frame.suggested_model ?? null,
                autoAction: frame.auto_action ?? 'none',
              },
            });
            break;
          case 'permission_request':
            dispatch({
              type: 'PERMISSION_REQUEST',
              session: sessionName,
              requestId: frame.request_id,
              kind: frame.kind,
              title: frame.title,
              description: frame.description,
              options: frame.options,
              questions: frame.questions ?? undefined,
              toolName: frame.tool_name ?? undefined,
            });
            break;
          case 'turn_state':
            dispatch({
              type: 'TURN_STATE',
              session: sessionName,
              running: frame.running,
            });
            streamDebug('turn', sessionName, frame.running ? 'turn start' : 'turn end');
            if (!frame.running) {
              queueMicrotask(() => {
                void (async () => {
                  mergeTranscriptRef.current(sessionName).catch(() => {});
                  await new Promise((r) => setTimeout(r, 50));
                  const after = stateRef.current.sessions[sessionName];
                  if (
                    after &&
                    (hasEmptyStreamingAssistant(after) || needsTranscriptBackfill(after))
                  ) {
                    syncTranscriptRef.current(sessionName, true).catch(() => {});
                  }
                })();
              });
            }
            break;
          case 'sub_agent':
            dispatch({
              type: 'SUBAGENT',
              session: sessionName,
              agentId: frame.agent_id,
              name: frame.name,
              description: frame.description,
              phase: frame.phase,
              ok: frame.ok ?? undefined,
              activity: frame.activity ?? undefined,
            });
            break;
          case 'watchdog_report':
            dispatch({
              type: 'WATCHDOG_REPORT',
              session: sessionName,
              phase: frame.phase,
              text: frame.text,
              detail: frame.detail,
              diagnostics: frame.diagnostics,
            });
            break;
          case 'context_recovery':
            dispatch({
              type: 'CONTEXT_RECOVERY',
              session: sessionName,
              recovered: frame.recovered,
              detail: frame.detail,
            });
            break;
          case 'ask_start':
            dispatch({
              type: 'ASK_START',
              session: sessionName,
              questionId: frame.question_id,
              question: frame.question,
              askKind: frame.kind ?? 'ask',
            });
            break;
          case 'ask_chunk':
            dispatch({
              type: 'ASK_CHUNK',
              session: sessionName,
              questionId: frame.question_id,
              text: frame.text,
            });
            break;
          case 'ask_done':
            dispatch({
              type: 'ASK_DONE',
              session: sessionName,
              questionId: frame.question_id,
              ok: frame.ok,
            });
            break;
          case 'slash_command_card':
            // A compact result card also closes any open "Compacting…" spinner.
            if (frame.kind === 'compact' && stateRef.current.sessions[sessionName]?.compacting) {
              dispatch({ type: 'COMPACT_STATE', session: sessionName, phase: 'done' });
            }
            dispatch({
              type: 'SLASH_CMD',
              session: sessionName,
              kind: frame.kind,
              title: frame.title,
              body: frame.body,
              data: frame.data,
            });
            if (frame.kind === 'compact') {
              void ensureSessionWsReady(sessionName).catch((err) => {
                console.warn('[DevScope] ensure_session_ws after compact failed:', err);
              });
            }
            break;
          case 'todo_update':
            dispatch({
              type: 'TODO_UPDATE',
              session: sessionName,
              turnId: frame.turn_id ?? undefined,
              todos: frame.todos,
            });
            break;
          case 'msg_ack': {
            // Contract 1: the bridge accepted our user_msg — close the loop.
            ackCapableRef.current = true;
            const timer = msgAckTimersRef.current.get(frame.client_msg_id);
            if (timer) {
              clearTimeout(timer);
              msgAckTimersRef.current.delete(frame.client_msg_id);
            }
            sentFramesRef.current.delete(frame.client_msg_id);
            dispatch({
              type: 'MSG_DELIVERY',
              session: sessionName,
              clientMsgId: frame.client_msg_id,
              delivery: 'delivered',
            });
            break;
          }
          case 'perm_ack': {
            // Contract 1: decision reached the bridge — only NOW flip the card.
            ackCapableRef.current = true;
            const entry = permPendingRef.current.get(frame.request_id);
            if (entry) {
              clearTimeout(entry.timer);
              permPendingRef.current.delete(frame.request_id);
            }
            dispatch({ type: 'PERMISSION_RESOLVE', session: sessionName, requestId: frame.request_id });
            if (entry && ['approve', 'allow_once', 'submit'].includes(entry.optionId)) {
              dispatch({ type: 'ACTIVITY', session: sessionName, label: 'Thinking…' });
            }
            break;
          }
          default:
            break;
        }
      }
    }

    chrome.runtime.onMessage.addListener(handleMessage);
    return () => chrome.runtime.onMessage.removeListener(handleMessage);
  }, []);

  // Clear all pending ack timers on unmount.
  useEffect(() => {
    const msgTimers = msgAckTimersRef.current;
    const permPending = permPendingRef.current;
    return () => {
      for (const timer of msgTimers.values()) clearTimeout(timer);
      msgTimers.clear();
      for (const entry of permPending.values()) clearTimeout(entry.timer);
      permPending.clear();
    };
  }, []);

  // ─── Actions ─────────────────────────────────────────────────────────────

  /** Arm the C3 rollback: no msg_ack within ACK_TIMEOUT_MS → "not delivered — retry". */
  const startMsgAckTimer = useCallback((sessionName: string, clientMsgId: string) => {
    const existing = msgAckTimersRef.current.get(clientMsgId);
    if (existing) clearTimeout(existing);
    const timer = setTimeout(() => {
      msgAckTimersRef.current.delete(clientMsgId);
      // Old bridges never ack — only roll back once we KNOW this bridge acks.
      if (!ackCapableRef.current) return;
      dispatch({ type: 'MSG_DELIVERY', session: sessionName, clientMsgId, delivery: 'failed' });
    }, ACK_TIMEOUT_MS);
    msgAckTimersRef.current.set(clientMsgId, timer);
  }, []);

  const switchSession = useCallback((name: string) => {
    dispatch({ type: 'SET_ACTIVE', name });
    loadBoundTab(name)
      .then(async (tab) => {
        dispatch({ type: 'SET_BOUND_TAB', session: name, tab });
        const prefs = await loadContextPrefs().catch(() => ({ autoBindFocusedTab: false, autoCompactEvery: 0 }));
        if (!tab && prefs.autoBindFocusedTab) {
          const bound = await tryAutoBindIfEmpty(name, true);
          if (bound) dispatch({ type: 'TAB_BOUND_ACK', session: name, tab: bound });
        }
      })
      .catch(() => {});
    const sessions = { ...stateRef.current.sessions };
    const keepOpen = collectWsKeepOpen(name, sessions);
    syncWsKeepalive(keepOpen).catch(() => {});
    mergeTranscriptRef.current(name).catch(() => {});
  }, []);

  const reconnectSession = useCallback(async (name: string) => {
    dispatch({ type: 'SET_RECONNECTING', value: true });
    try {
      await wakeOffscreen();
      await chrome.runtime.sendMessage({ kind: 'reset_session_ws', sessionName: name });
      await chrome.runtime.sendMessage({ kind: 'ensure_session_ws', sessionName: name });
    } catch {
      /* non-fatal — UI still shows offline until status frame arrives */
    } finally {
      dispatch({ type: 'SET_RECONNECTING', value: false });
    }
    switchSession(name);
  }, [switchSession]);

  const bindSessionTab = useCallback(async (sessionName: string, tabId: number) => {
    const tab = await bindTabById(sessionName, tabId);
    if (tab) dispatch({ type: 'TAB_BOUND_ACK', session: sessionName, tab });
    else dispatch({ type: 'SET_BOUND_TAB', session: sessionName, tab: null });
  }, []);

  const setBoundTabState = useCallback((
    sessionName: string,
    tab: import('@/shared/tabBinding').BoundTab | null,
    opts?: { silent?: boolean },
  ) => {
    const prev = stateRef.current.sessions[sessionName]?.boundTab;
    if (tab && !opts?.silent && (!prev || prev.tabId !== tab.tabId)) {
      dispatch({ type: 'TAB_BOUND_ACK', session: sessionName, tab });
    } else {
      dispatch({ type: 'SET_BOUND_TAB', session: sessionName, tab });
    }
  }, []);

  const clearTabPick = useCallback((sessionName: string) => {
    dispatch({ type: 'CLEAR_TAB_PICK', session: sessionName });
  }, []);

  const prepareOutboundContext = useCallback(
    async (sessionName: string, text: string, initialContext?: MessageContext) => {
      try {
        const contextPrefs = await loadContextPrefs().catch(() => ({
          autoCompactEvery: 0,
          autoBindFocusedTab: false,
        }));
        if (contextPrefs.autoBindFocusedTab) {
          const bound = await tryAutoBindIfEmpty(sessionName, true).catch(() => null);
          if (bound) {
            const prev = stateRef.current.sessions[sessionName]?.boundTab;
            if (!prev || prev.tabId !== bound.tabId) {
              dispatch({ type: 'TAB_BOUND_ACK', session: sessionName, tab: bound });
            } else {
              dispatch({ type: 'SET_BOUND_TAB', session: sessionName, tab: bound });
            }
          }
        }

        const bindResult = await autoBindTabFromText(sessionName, text).catch(
          () => ({ status: 'none' as const }),
        );
        if (bindResult.status === 'bound') {
          dispatch({ type: 'SET_BOUND_TAB', session: sessionName, tab: bindResult.tab });
        } else if (bindResult.status === 'ambiguous') {
          dispatch({
            type: 'SET_TAB_PICK',
            session: sessionName,
            reason: 'Several tabs match your link — which should I control?',
            hintUrl: bindResult.hintUrl,
            candidates: bindResult.candidates,
          });
        }

        let enrichedContext = await enrichContextWithBoundTab(sessionName, initialContext).catch(
          () => initialContext,
        );
        enrichedContext = await persistOutboxAttachments(sessionName, enrichedContext).catch(
          () => enrichedContext,
        );
        return enrichedContext;
      } catch (err) {
        console.warn('[DevScope] prepareOutboundContext error:', err);
        return initialContext;
      }
    },
    [],
  );

  const sendMessage = useCallback(
    async (
      sessionName: string,
      text: string,
      opts?: { context?: MessageContext; mode?: AgentMode; model?: string },
    ) => {
      const id = `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
      const initialContext = opts?.context;
      const hasInitialContext = Boolean(
        initialContext?.elements?.length ||
          initialContext?.attachments?.length ||
          initialContext?.boundTab,
      );
      const displayText = text.trim() || (hasInitialContext ? '' : '(attached page context)');

      const session = stateRef.current.sessions[sessionName];
      const agent = session?.agent ?? 'claude';
      const isWorking = session ? isSessionWorking(session) : false;
      const isControl = isSessionControlCommand(text);

      // Show the user bubble immediately — binding/WS prep can take seconds.
      if (isControl) {
        dispatch({
          type: 'SESSION_COMMAND',
          session: sessionName,
          id,
          text: displayText,
          hint: sessionControlHint(text),
        });
      } else {
        dispatch(
          isWorking
            ? {
                type: 'APPEND_QUEUED',
                session: sessionName,
                id,
                text: displayText,
                context: initialContext,
              }
            : {
                type: 'APPEND_USER',
                session: sessionName,
                id,
                text: displayText,
                context: initialContext,
              },
        );
      }

      await wakeOffscreen().catch(() => {});
      await ensureSessionWsReady(sessionName).catch((err) => {
        console.warn('[DevScope] ensure_session_ws before send failed:', err);
      });

      // Context enrichment (tab bind / storage) must NEVER block delivery — quota
      // exceeded or a stuck SW used to abort here after the optimistic bubble.
      let enrichedContext = opts?.context;
      try {
        enrichedContext = await prepareOutboundContext(sessionName, text, opts?.context);
      } catch (err) {
        console.warn('[DevScope] prepareOutboundContext failed — sending without enrichment:', err);
      }

      let coachPrefs = { enabled: false, lang: 'he', focus: [] as string[] };
      try {
        coachPrefs = await loadCoachPrefs();
      } catch {
        /* defaults */
      }
      const frame: UserMsg = {
        type: 'user_msg',
        agent,
        text,
        context: enrichedContext,
        mode: opts?.mode,
        model: opts?.model,
        coach_enabled: coachPrefs.enabled,
        coach_lang: coachPrefs.lang,
        coach_focus: coachPrefs.focus,
        client_msg_id: id,
      };
      if (!isControl) {
        sentFramesRef.current.set(id, frame);
        startMsgAckTimer(sessionName, id);
      }
      chrome.runtime
        .sendMessage({ kind: 'send_to_bridge', sessionName, frame })
        .catch((err) => {
          console.warn('[DevScope] send_to_bridge failed:', err);
          // Local send failure is definitive — roll back regardless of ack support.
          if (!isControl) {
            dispatch({ type: 'MSG_DELIVERY', session: sessionName, clientMsgId: id, delivery: 'failed' });
          }
        });
    },
    [prepareOutboundContext, startMsgAckTimer],
  );

  /** Resend a message whose delivery failed (or a dropped steering message). */
  const retryMessage = useCallback(
    async (sessionName: string, messageId: string): Promise<void> => {
      await wakeOffscreen().catch(() => {});
      const session = stateRef.current.sessions[sessionName];
      const msg = session?.messages.find((m) => m.id === messageId && m.role === 'user');
      if (!msg) return;
      const frame: UserMsg = sentFramesRef.current.get(messageId) ?? {
        type: 'user_msg',
        agent: session?.agent ?? 'claude',
        text: msg.text,
        context: msg.context,
        client_msg_id: messageId,
      };
      dispatch({ type: 'MSG_DELIVERY', session: sessionName, clientMsgId: messageId, delivery: 'pending' });
      startMsgAckTimer(sessionName, messageId);
      chrome.runtime
        .sendMessage({ kind: 'send_to_bridge', sessionName, frame })
        .catch(() => {
          dispatch({ type: 'MSG_DELIVERY', session: sessionName, clientMsgId: messageId, delivery: 'failed' });
        });
    },
    [startMsgAckTimer],
  );

  /** ✕ on a queued steering bubble: remove locally while it is still cancellable. */
  const cancelSteering = useCallback((sessionName: string, messageId: string) => {
    const session = stateRef.current.sessions[sessionName];
    const msg = session?.messages.find((m) => m.id === messageId && m.steering);
    if (!msg) return;
    if (msg.delivery === 'delivered') {
      // The bridge already wrote it to the agent — removing the bubble would lie.
      dispatch({
        type: 'SESSION_COMMAND',
        session: sessionName,
        id: `steer-cancel-${Date.now()}`,
        text: 'Cancel queued message',
        hint: 'Already delivered to the agent — it will run. Use Stop to interrupt instead.',
      });
      return;
    }
    dispatch({ type: 'CANCEL_STEERING', session: sessionName, messageId });
  }, []);

  const dismissCompactBanner = useCallback((sessionName: string) => {
    const tokens = stateRef.current.sessions[sessionName]?.usageTotal?.tokens ?? 0;
    dispatch({ type: 'COMPACT_BANNER_DISMISS', session: sessionName, tokens });
  }, []);

  const sendMessageViaPty = useCallback(
    async (
      sessionName: string,
      text: string,
      terminalRef: RefObject<TerminalViewHandle | null>,
      opts?: { context?: MessageContext; mode?: AgentMode; model?: string },
    ) => {
      await wakeOffscreen().catch(() => {});

      const enrichedContext = await prepareOutboundContext(sessionName, text, opts?.context);
      const session = stateRef.current.sessions[sessionName];
      const payload = formatPtyUserTurn(text, enrichedContext, {
        mode: opts?.mode,
        model: opts?.model,
        claudeAgent: session?.claude_agent,
      });

      const waitForPty = async (): Promise<TerminalViewHandle | null> => {
        for (let i = 0; i < 30; i += 1) {
          const handle = terminalRef.current;
          if (handle?.isOpen()) return handle;
          await new Promise((r) => window.setTimeout(r, 100));
        }
        return terminalRef.current;
      };

      const handle = await waitForPty();
      if (!handle?.isOpen()) {
        console.warn('[DevScope] PTY not connected — message not sent');
        return;
      }
      handle.write(`${payload}\r`);
    },
    [prepareOutboundContext],
  );

  const createSession = useCallback(async (payload: CreateSessionPayload): Promise<void> => {
    const token = await getToken();
    const res = await fetch(`${BRIDGE_HTTP}/sessions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({})) as { detail?: string };
      throw new Error(body.detail ?? `HTTP ${res.status}`);
    }
    dispatch({
      type: 'ADD_SESSION',
      name: payload.name,
      agent: payload.agent,
      cwd: payload.cwd,
      purpose: payload.purpose ?? 'chat',
    });
    await wakeOffscreen().catch(() => {});
  }, []);

  const deleteSession = useCallback(async (name: string): Promise<void> => {
    const token = await getToken();
    await fetch(`${BRIDGE_HTTP}/sessions/${encodeURIComponent(name)}`, {
      method: 'DELETE',
      headers: authHeaders(token),
    });
    dispatch({ type: 'REMOVE_SESSION', name });
    chrome.runtime.sendMessage({ kind: 'close_session_ws', sessionName: name }).catch(() => {});
    await clearHistory(name);
  }, []);

  const interrupt = useCallback(async (name: string): Promise<void> => {
    dispatch({ type: 'DONE', session: name });
    dispatch({ type: 'TURN_STATE', session: name, running: false });
    const hadTurn = await interruptSession(name);
    if (hadTurn) {
      dispatch({ type: 'TURN_INTERRUPTED', session: name });
    }
    window.setTimeout(() => {
      mergeTranscriptRef.current(name).catch(() => {});
      syncTranscriptRef.current(name, true).catch(() => {});
    }, 400);
    window.setTimeout(() => {
      mergeTranscriptRef.current(name).catch(() => {});
    }, 2500);
  }, []);

  // Recover a stuck session: kill the hung backend process without wiping metadata/history.
  const resetSession = useCallback(async (name: string): Promise<void> => {
    const session = stateRef.current.sessions[name];
    if (!session) return;
    const savedMessages = session.messages;
    dispatch({ type: 'DONE', session: name });
    dispatch({ type: 'TURN_STATE', session: name, running: false });
    await resetSessionBridge(name).catch(() => {});
    dispatch({ type: 'SET_HISTORY', name, messages: savedMessages, force: true });
    await wakeOffscreen().catch(() => {});
    syncWsKeepalive(collectWsKeepOpen(name, { ...stateRef.current.sessions, [name]: session })).catch(
      () => {},
    );
    window.setTimeout(() => {
      syncTranscriptRef.current(name, true).catch(() => {});
    }, 800);
  }, []);

  const respondPermission = useCallback(
    async (
      sessionName: string,
      requestId: string,
      optionId: string,
      extras?: { answers?: Record<string, string | string[]>; custom_text?: string },
    ): Promise<void> => {
      await wakeOffscreen().catch(() => {});
      // Mark the card "sending" — it flips to resolved only on perm_ack (C3).
      dispatch({ type: 'PERM_DELIVERY', session: sessionName, requestId, state: 'sending' });
      const timer = setTimeout(() => {
        permPendingRef.current.delete(requestId);
        if (!ackCapableRef.current) {
          // Old bridge (no acks): fall back to the legacy optimistic resolve.
          dispatch({ type: 'PERMISSION_RESOLVE', session: sessionName, requestId });
          if (['approve', 'allow_once', 'submit'].includes(optionId)) {
            dispatch({ type: 'ACTIVITY', session: sessionName, label: 'Thinking…' });
          }
          return;
        }
        // Ack-capable bridge stayed silent — restore the card with an error note.
        dispatch({ type: 'PERM_DELIVERY', session: sessionName, requestId, state: 'failed' });
      }, ACK_TIMEOUT_MS);
      permPendingRef.current.set(requestId, { session: sessionName, optionId, timer });
      chrome.runtime
        .sendMessage({
          kind: 'send_to_bridge',
          sessionName,
          frame: {
            type: 'permission_response',
            request_id: requestId,
            option_id: optionId,
            answers: extras?.answers,
            custom_text: extras?.custom_text,
          },
        })
        .catch((err) => {
          console.warn('[DevScope] permission_response failed:', err);
          const entry = permPendingRef.current.get(requestId);
          if (entry) {
            clearTimeout(entry.timer);
            permPendingRef.current.delete(requestId);
          }
          dispatch({ type: 'PERM_DELIVERY', session: sessionName, requestId, state: 'failed' });
        });
      window.setTimeout(() => {
        mergeTranscriptRef.current(sessionName).catch(() => {});
      }, 2000);
      window.setTimeout(() => {
        mergeTranscriptRef.current(sessionName).catch(() => {});
      }, 8000);
    },
    [],
  );

  return {
    state,
    dispatch,
    switchSession,
    reconnectSession,
    sendMessage,
    sendMessageViaPty,
    retryMessage,
    cancelSteering,
    createSession,
    deleteSession,
    interrupt,
    resetSession,
    respondPermission,
    refreshSessions,
    syncTranscript,
    mergeTranscript,
    bindSessionTab,
    clearTabPick,
    setBoundTabState,
    setTerminalModeSession,
    compactSession,
    dismissCompactBanner,
  };
}
