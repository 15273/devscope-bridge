/**
 * reduceLifecycle.ts — session list, composer send, tab binding, view.
 */
import { nextId, nowIso, updateSession } from './helpers';
import { applyLivenessFields } from './reliabilityActions';
import {
  applyTurnIdleCleanup,
  newAssistantMsg,
  sessionHasStaleWorkingState,
} from './sessionHelpers';
import type { SessionState, StoreAction, StoreState } from './sessionTypes';

export function reduceLifecycle(state: StoreState, action: StoreAction): StoreState | undefined {
  switch (action.type) {
    case 'SET_SESSIONS': {
      const next: Record<string, SessionState> = {};
      for (const [name, info] of Object.entries(action.infos)) {
        const existing = state.sessions[name];
        let session: SessionState = existing
          ? {
              ...existing,
              lastUsed: info.last_used,
              agent: info.agent ?? existing.agent,
              cwd: info.cwd ?? existing.cwd,
              model: info.model ?? existing.model ?? null,
              purpose: info.purpose ?? existing.purpose,
              turnRunning: info.turn_running ?? false,
            }
          : {
              name,
              agent: info.agent ?? 'claude',
              cwd: info.cwd ?? '',
              purpose: info.purpose ?? 'chat',
              model: info.model ?? null,
              lastUsed: info.last_used,
              messages: [],
              isConnected: false,
              isLoadingHistory: true,
              turnRunning: info.turn_running ?? false,
            };
        // Bridge says the turn ended — clear stale working UI (missed turn_state WS frames).
        if (existing && info.turn_running === false && sessionHasStaleWorkingState(existing)) {
          session = applyTurnIdleCleanup(session);
        }
        // Bridge says a turn started while the UI lost track (e.g. PTY / missed frames).
        if (existing && info.turn_running === true && !existing.turnStartedAt) {
          session = {
            ...session,
            turnStartedAt: Date.now(),
            activity: session.activity ?? 'Working…',
          };
        }
        // Liveness fields (contract 2) — absent on old bridges, authoritative when sent.
        session = applyLivenessFields(session, info);
        next[name] = session;
      }
      const activeStillExists = state.activeSession && next[state.activeSession];
      const newActive = activeStillExists
        ? state.activeSession
        : Object.keys(next)[0] ?? null;
      return { ...state, sessions: next, activeSession: newActive };
    }

    case 'ADD_SESSION': {
      const session: SessionState = {
        name: action.name,
        agent: action.agent,
        cwd: action.cwd,
        purpose: action.purpose ?? 'chat',
        lastUsed: new Date().toISOString(),
        messages: [],
        isConnected: false,
        isLoadingHistory: false,
      };
      return {
        ...state,
        sessions: { ...state.sessions, [action.name]: session },
        activeSession: action.name,
      };
    }

    case 'REMOVE_SESSION': {
      const { [action.name]: _removed, ...rest } = state.sessions;
      const names = Object.keys(rest);
      const newActive =
        state.activeSession === action.name ? (names[0] ?? null) : state.activeSession;
      return { ...state, sessions: rest, activeSession: newActive };
    }

    case 'SET_ACTIVE':
      return { ...state, activeSession: action.name };

    case 'SET_HISTORY':
      return updateSession(state, action.name, (s) => {
        // Ignore stale history loads after the user already sent a message.
        if (!action.force && !s.isLoadingHistory) return s;
        return {
          ...s,
          messages: action.messages,
          isLoadingHistory: false,
        };
      });

    case 'SESSION_STATUS':
      return updateSession(state, action.name, (s) => ({
        ...s,
        isConnected: action.connected,
        ...(action.connected ? { browserExtensionDisconnected: false } : {}),
      }));

    case 'APPEND_USER':
      return updateSession(state, action.session, (s) => ({
        ...s,
        isLoadingHistory: false,
        activity: 'Thinking…',
        turnStartedAt: Date.now(),
        messages: [
          ...s.messages,
          {
            id: action.id,
            role: 'user',
            text: action.text,
            context: action.context,
            isStreaming: false,
            isError: false,
            createdAt: nowIso(),
            delivery: 'pending',
          },
          newAssistantMsg(),
        ],
      }));

    case 'APPEND_QUEUED':
      // A steering message sent mid-turn: claude queues it and runs it as its
      // OWN turn after the current one. Add just the user bubble (no assistant
      // placeholder — the queued turn's first chunk opens its own bubble).
      return updateSession(state, action.session, (s) => ({
        ...s,
        isLoadingHistory: false,
        messages: [
          ...s.messages,
          {
            id: action.id,
            role: 'user',
            text: action.text,
            context: action.context,
            isStreaming: false,
            isError: false,
            createdAt: nowIso(),
            steering: true,
            delivery: 'pending',
          },
        ],
        steeringQueue: [...(s.steeringQueue ?? []), action.id],
      }));

    case 'SESSION_COMMAND':
      return updateSession(state, action.session, (s) => ({
        ...s,
        isLoadingHistory: false,
        messages: [
          ...s.messages,
          {
            id: action.id,
            role: 'status',
            text: '',
            isStreaming: false,
            isError: false,
            createdAt: nowIso(),
            statusKind: 'session_command',
            statusDetail: `${action.text} — ${action.hint}`,
          },
        ],
      }));

    case 'SET_BOUND_TAB':
      return updateSession(state, action.session, (s) => ({
        ...s,
        boundTab: action.tab,
        tabPickPrompt: undefined,
      }));

    case 'TAB_BOUND_ACK':
      return updateSession(state, action.session, (s) => ({
        ...s,
        boundTab: action.tab,
        tabPickPrompt: undefined,
        messages: [
          ...s.messages,
          {
            id: nextId(),
            role: 'status',
            text: '',
            isStreaming: false,
            isError: false,
            createdAt: nowIso(),
            statusKind: 'bound_tab',
            statusDetail: action.tab.title || action.tab.url,
          },
        ],
      }));

    case 'SET_TAB_PICK':
      return updateSession(state, action.session, (s) => ({
        ...s,
        tabPickPrompt: {
          reason: action.reason,
          hintUrl: action.hintUrl,
          candidates: action.candidates,
        },
      }));

    case 'CLEAR_TAB_PICK':
      return updateSession(state, action.session, (s) => ({
        ...s,
        tabPickPrompt: undefined,
      }));

    case 'SET_RECONNECTING':
      return { ...state, reconnecting: action.value };

    case 'SET_SESSION_MODEL':
      return updateSession(state, action.session, (s) => ({
        ...s,
        model: action.model,
      }));

    case 'SET_VIEW':
      return { ...state, view: action.view };

    default:
      return undefined;
  }
}
