/**
 * reduceStream.ts — live turn: chunks, tools, permissions, turn state.
 */
import { isBrowserExtensionDisconnectedError } from '../utils/browserDisconnect';
import { nextId, nowIso, updateSession } from './helpers';
import { flushNextSteering } from './reliabilityActions';
import {
  applyTurnIdleCleanup,
  attachTurnId,
  finalizeOrphanRunningTools,
  findTurnAssistantIdx,
  lastStreamingAssistantIdx,
  newAssistantMsg,
  newTurnAssistantMsg,
} from './sessionHelpers';
import type { ChatMessage, StoreAction, StoreState } from './sessionTypes';
import { upsertToolCallRow } from './toolActivityReducer';
import {
  appendTextDelta,
  appendThinkingDelta,
  markThinkingDone,
  segmentsText,
} from './turnSegments';

export function reduceStream(state: StoreState, action: StoreAction): StoreState | undefined {
  switch (action.type) {
    case 'PERMISSION_REQUEST': {
      const needsDecision =
        (action.kind === 'plan' || action.kind === 'ask_user' || action.kind === 'tool_blocked')
        && action.options.length > 0;
      return updateSession(state, action.session, (s) => {
        // Dedupe: pending-recovery fetches (C4) may replay a request the panel
        // already rendered from the live WS frame.
        if (s.messages.some((m) => m.role === 'permission' && m.actionId === action.requestId)) {
          return s;
        }
        const msgs = [...s.messages];
        const streamIdx = lastStreamingAssistantIdx(msgs);
        if (streamIdx >= 0) {
          msgs[streamIdx] = { ...msgs[streamIdx], isStreaming: false };
        }
        return {
          ...s,
          messages: [
            ...msgs,
            {
              id: nextId(),
              role: 'permission',
              text: action.description,
              isStreaming: false,
              isError: false,
              createdAt: nowIso(),
              actionId: action.requestId,
              permKind: action.kind,
              permTitle: action.title,
              permOptions: action.options,
              permQuestions: action.questions,
              permToolName: action.toolName,
              permResolved: action.kind === 'permission_denied',
            },
          ],
          activity: needsDecision
            ? (action.kind === 'ask_user' ? 'Waiting for your answers' : 'Waiting for your approval')
            : s.activity,
          turnStartedAt: needsDecision ? undefined : s.turnStartedAt,
          awaitingKind: needsDecision ? action.kind : s.awaitingKind,
        };
      });
    }

    case 'TURN_STATE':
      return updateSession(state, action.session, (s) => {
        const turnEnded = !action.running;
        if (!turnEnded) {
          return {
            ...s,
            turnRunning: true,
            turnStartedAt: s.turnStartedAt ?? Date.now(),
            activity: s.activity ?? 'Working…',
          };
        }
        return {
          ...applyTurnIdleCleanup(s),
          turnRunning: false,
        };
      });

    case 'TURN_INTERRUPTED':
      return updateSession(state, action.session, (s) => {
        const statusMsg: ChatMessage = {
          id: nextId(),
          role: 'status',
          text: '',
          isStreaming: false,
          isError: false,
          createdAt: nowIso(),
          statusKind: 'interrupted',
          statusDetail: 'היסטוריית הצ׳אט נשמרה — אפשר להמשיך לשלוח הודעות.',
        };
        const msgs = finalizeOrphanRunningTools(
          s.messages.map((m) =>
            m.role === 'assistant' && m.isStreaming ? { ...m, isStreaming: false } : m,
          ),
        );
        return {
          ...s,
          messages: [...msgs, statusMsg],
          turnRunning: false,
          turnStartedAt: undefined,
          activity: undefined,
        };
      });

    case 'FORCE_TURN_IDLE':
      return updateSession(state, action.session, (s) => ({
        ...applyTurnIdleCleanup(s, true),
        turnRunning: false,
      }));

    case 'PERMISSION_RESOLVE':
      return updateSession(state, action.session, (s) => ({
        ...s,
        awaitingKind: null,
        activity:
          s.activity === 'Waiting for your approval' ||
          s.activity === 'Waiting for your answers'
            ? undefined
            : s.activity,
        messages: s.messages.map((m) =>
          m.role === 'permission' && m.actionId === action.requestId
            ? { ...m, permResolved: true, permDelivery: undefined }
            : m,
        ),
      }));

    case 'SUBAGENT':
      return updateSession(state, action.session, (s) => {
        const msgs = [...s.messages];
        let idx = lastStreamingAssistantIdx(msgs);
        if (idx < 0) {
          for (let i = msgs.length - 1; i >= 0; i--) {
            if (msgs[i].role === 'assistant') {
              idx = i;
              break;
            }
          }
        }
        if (idx < 0) return s;
        const rows = [...(msgs[idx].subAgents ?? [])];
        const at = rows.findIndex((r) => r.agentId === action.agentId);
        if (action.phase === 'start') {
          if (at < 0) {
            rows.push({
              agentId: action.agentId,
              name: action.name,
              description: action.description,
              phase: 'start',
            });
          }
        } else if (at >= 0) {
          rows[at] = {
            ...rows[at],
            phase: action.phase,
            ok: action.phase === 'done' ? action.ok : rows[at].ok,
            activity: action.activity ?? rows[at].activity,
          };
        }
        msgs[idx] = { ...msgs[idx], subAgents: rows };
        return { ...s, messages: msgs };
      });

    case 'ACTIVITY':
      return updateSession(state, action.session, (s) => ({ ...s, activity: action.label }));

    case 'TOOL_CALL':
      // A tool call lifecycle event (running → done/error), correlated by call_id.
      // The first (running) event inserts one permanent transcript row; the later
      // done/error event for the SAME call_id updates that row in place — never a
      // second disconnected message.
      return updateSession(state, action.session, (s) => {
        const messages = upsertToolCallRow(s.messages, action.activity, { nextId, nowIso });
        const detail = action.activity.detail ?? '';
        const disconnect =
          action.activity.status === 'error' && isBrowserExtensionDisconnectedError(detail);
        return {
          ...s,
          messages,
          ...(disconnect ? { browserExtensionDisconnected: true } : {}),
        };
      });

    case 'USAGE':
      return updateSession(state, action.session, (s) => ({
        ...s,
        contextTokens: action.inputTokens,
        usageTotal: {
          tokens: (s.usageTotal?.tokens ?? 0) + action.tokens,
          costUsd: (s.usageTotal?.costUsd ?? 0) + action.costUsd,
        },
      }));

    case 'CHUNK':
      return updateSession(state, action.session, (s) => {
        const msgs = [...s.messages];
        if (action.turnId) {
          const turnId = action.turnId;
          const blockIndex = action.blockIndex ?? 0;
          const idx = findTurnAssistantIdx(msgs, turnId);
          if (idx >= 0) {
            const base = attachTurnId(msgs[idx], turnId);
            const segments = appendTextDelta(base.segments ?? [], blockIndex, action.text, Date.now());
            msgs[idx] = { ...base, segments, text: segmentsText(segments) };
            return { ...s, messages: msgs };
          }
          const steeringQueue = flushNextSteering(s, msgs);
          const segments = appendTextDelta([], blockIndex, action.text, Date.now());
          msgs.push({ ...newTurnAssistantMsg(turnId), segments, text: segmentsText(segments) });
          return { ...s, messages: msgs, steeringQueue };
        }
        // Legacy path (no turn_id) — behaves exactly as before Task 5.
        const idx = lastStreamingAssistantIdx(msgs);
        if (idx >= 0) {
          msgs[idx] = { ...msgs[idx], text: msgs[idx].text + action.text };
          return { ...s, messages: msgs };
        }
        // A queued (steering) turn started — flush by client_msg_id (FIFO),
        // then open a fresh assistant bubble.
        const steeringQueue = flushNextSteering(s, msgs);
        msgs.push(newAssistantMsg(action.text));
        return { ...s, messages: msgs, steeringQueue };
      });

    case 'THINKING_CHUNK':
      return updateSession(state, action.session, (s) => {
        const msgs = [...s.messages];
        const idx = action.turnId
          ? findTurnAssistantIdx(msgs, action.turnId)
          : lastStreamingAssistantIdx(msgs);
        if (idx >= 0) {
          const base = action.turnId ? attachTurnId(msgs[idx], action.turnId) : msgs[idx];
          const segments = appendThinkingDelta(base.segments ?? [], action.text, Date.now());
          msgs[idx] = { ...base, segments };
          return { ...s, messages: msgs };
        }
        if (!action.turnId) return s; // No bubble to attach to and no id to create one — drop.
        const steeringQueue = flushNextSteering(s, msgs);
        const segments = appendThinkingDelta([], action.text, Date.now());
        msgs.push({ ...newTurnAssistantMsg(action.turnId), segments });
        return { ...s, messages: msgs, steeringQueue };
      });

    case 'TURN_RESULT':
      return updateSession(state, action.session, (s) => {
        const msgs = [...s.messages];
        let idx = action.turnId
          ? msgs.findIndex((m) => m.role === 'assistant' && m.turnId === action.turnId)
          : -1;
        if (idx < 0) idx = lastStreamingAssistantIdx(msgs);
        if (idx < 0) return s; // Unknown turn and nothing streaming — drop silently.
        msgs[idx] = { ...msgs[idx], turnMeta: action.meta };
        return { ...s, messages: msgs };
      });

    case 'DONE':
      return updateSession(state, action.session, (s) => {
        let msgs = [...s.messages];
        const idx = lastStreamingAssistantIdx(msgs);
        if (idx >= 0) {
          const segments = msgs[idx].segments;
          msgs[idx] = {
            ...msgs[idx],
            isStreaming: false,
            ...(segments ? { segments: markThinkingDone(segments, Date.now()) } : {}),
          };
        }
        msgs = finalizeOrphanRunningTools(msgs);
        // Do not clear turnRunning here — ai_done is per assistant segment; TURN_STATE
        // from the bridge is the source of truth for whether the turn is still active.
        // BUT when the bridge never reported a running turn, there is nothing left
        // to wait for — clear the spinner state so "Thinking…" cannot persist.
        if (s.turnRunning) return { ...s, messages: msgs };
        return { ...s, messages: msgs, activity: undefined, turnStartedAt: undefined };
      });

    case 'ERROR':
      return updateSession(state, action.session, (s) => {
        let msgs = [...s.messages];
        const idx = lastStreamingAssistantIdx(msgs);
        if (idx >= 0) {
          msgs[idx] = { ...msgs[idx], text: action.text, isStreaming: false, isError: true };
        } else {
          msgs.push({ id: nextId(), role: 'assistant', text: action.text, isStreaming: false, isError: true, createdAt: nowIso() });
        }
        msgs = finalizeOrphanRunningTools(msgs);
        return { ...s, messages: msgs, activity: undefined, turnStartedAt: undefined, turnRunning: false };
      });

    case 'TOOL_ACTIVITY':
      return updateSession(state, action.session, (s) => {
        const msgs = [...s.messages];
        if (action.phase === 'done') {
          const idx = msgs.findIndex((m) => m.role === 'tool' && m.actionId === action.actionId);
          const summary = action.summary ?? (idx >= 0 ? msgs[idx].text : '');
          const failed = action.ok === false;
          const disconnect = failed && isBrowserExtensionDisconnectedError(summary);
          if (idx >= 0) {
            msgs[idx] = {
              ...msgs[idx],
              toolPhase: 'done',
              toolOk: action.ok,
              isError: failed,
              text: action.summary ?? msgs[idx].text,
            };
          }
          return {
            ...s,
            messages: msgs,
            ...(disconnect ? { browserExtensionDisconnected: true } : {}),
          };
        }
        const toolMsg: ChatMessage = {
          id: nextId(),
          role: 'tool',
          text: action.summary ?? '',
          isStreaming: false,
          isError: false,
          createdAt: nowIso(),
          tool: action.tool,
          actionId: action.actionId,
          toolPhase: 'start',
        };
        // Insert before a trailing streaming assistant message so CHUNK still
        // appends to that assistant message.
        const last = msgs[msgs.length - 1];
        if (last?.role === 'assistant' && last.isStreaming) {
          msgs.splice(msgs.length - 1, 0, toolMsg);
        } else {
          msgs.push(toolMsg);
        }
        return { ...s, messages: msgs };
      });

    default:
      return undefined;
  }
}
