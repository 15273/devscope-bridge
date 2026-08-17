/**
 * reduceTranscript.ts — history load/merge, side queries, slash cards, coach.
 */
import {
  backfillMessageText,
  buildMessagesFromTranscript,
  hasEmptyStreamingAssistant,
  mergeTranscriptIntoMessages,
} from '../utils/transcriptSync';
import { nextId, nowIso, updateSession } from './helpers';
import {
  finalizeOrphanRunningTools,
  insertSideQueryCard,
} from './sessionHelpers';
import type { ChatMessage, StoreAction, StoreState } from './sessionTypes';

export function reduceTranscript(state: StoreState, action: StoreAction): StoreState | undefined {
  switch (action.type) {
    case 'WATCHDOG_REPORT': {
      return updateSession(state, action.session, (s) => {
        const msgs = [...s.messages];
        if (action.phase === 'start') {
          // Open a new MedicCard bubble
          const medicMsg: ChatMessage = {
            id: nextId(),
            role: 'medic',
            text: action.text ?? '',
            isStreaming: true,
            isError: false,
            createdAt: nowIso(),
            medicPhase: 'running',
            medicTarget: action.session,
            medicDiagnostics: action.diagnostics,
          };
          msgs.push(medicMsg);
          return { ...s, messages: msgs, medicRunning: true };
        }
        if (action.phase === 'chunk') {
          // Append text to the last medic bubble
          const idx = [...msgs].reverse().findIndex((m) => m.role === 'medic' && m.isStreaming);
          const realIdx = idx >= 0 ? msgs.length - 1 - idx : -1;
          if (realIdx >= 0) {
            msgs[realIdx] = { ...msgs[realIdx], text: msgs[realIdx].text + (action.text ?? '') };
          }
          return { ...s, messages: msgs };
        }
        // phase === 'done' | 'error'
        const idx = [...msgs].reverse().findIndex((m) => m.role === 'medic' && m.isStreaming);
        const realIdx = idx >= 0 ? msgs.length - 1 - idx : -1;
        if (realIdx >= 0) {
          msgs[realIdx] = {
            ...msgs[realIdx],
            isStreaming: false,
            medicPhase: action.phase === 'done' ? 'healthy' : 'issue',
            medicOk: action.phase === 'done',
            text: msgs[realIdx].text + (action.text ?? ''),
          };
        }
        return { ...s, messages: msgs, medicRunning: false };
      });
    }

    case 'MEDIC_CHUNK': {
      // Route an ai_chunk that arrived while medicRunning=true to the MedicCard.
      return updateSession(state, action.session, (s) => {
        const msgs = [...s.messages];
        const idx = [...msgs].reverse().findIndex((m) => m.role === 'medic' && m.isStreaming);
        const realIdx = idx >= 0 ? msgs.length - 1 - idx : -1;
        if (realIdx >= 0) {
          msgs[realIdx] = { ...msgs[realIdx], text: msgs[realIdx].text + action.text };
        }
        return { ...s, messages: msgs };
      });
    }

    case 'ASK_START': {
      return updateSession(state, action.session, (s) => {
        const askMsg: ChatMessage = {
          id: nextId(),
          role: 'ask',
          text: '',
          isStreaming: true,
          isError: false,
          createdAt: nowIso(),
          questionId: action.questionId,
          askDone: false,
          askOk: undefined,
          askKind: action.askKind ?? 'ask',
          permTitle: action.question,
        };
        return { ...s, messages: insertSideQueryCard(s.messages, askMsg) };
      });
    }

    case 'ASK_CHUNK': {
      return updateSession(state, action.session, (s) => {
        const msgs = [...s.messages];
        const idx = msgs.findIndex((m) => m.role === 'ask' && m.questionId === action.questionId);
        if (idx >= 0) {
          msgs[idx] = { ...msgs[idx], text: msgs[idx].text + action.text };
        }
        return { ...s, messages: msgs };
      });
    }

    case 'ASK_DONE': {
      return updateSession(state, action.session, (s) => {
        const msgs = [...s.messages];
        const idx = msgs.findIndex((m) => m.role === 'ask' && m.questionId === action.questionId);
        if (idx >= 0) {
          msgs[idx] = { ...msgs[idx], isStreaming: false, askDone: true, askOk: action.ok };
        }
        return { ...s, messages: msgs };
      });
    }

    case 'CONTEXT_RECOVERY': {
      return updateSession(state, action.session, (s) => {
        if (!action.recovered) return s;
        const statusMsg: ChatMessage = {
          id: nextId(),
          role: 'status',
          text: '',
          isStreaming: false,
          isError: false,
          createdAt: nowIso(),
          statusKind: 'context_recovered',
          statusDetail: action.detail,
        };
        return { ...s, messages: [...s.messages, statusMsg] };
      });
    }

    case 'SLASH_CMD':
      return updateSession(state, action.session, (s) => {
        const card: ChatMessage = {
          id: nextId(),
          role: 'slash_cmd',
          text: action.body,
          isStreaming: false,
          isError: false,
          createdAt: nowIso(),
          slashKind: action.kind,
          slashTitle: action.title,
          slashData: action.data,
        };
        const modelFromCard =
          action.kind === 'model' && action.data && 'model' in action.data
            ? (action.data.model as string | null)
            : undefined;
        const resetUsage = action.kind === 'new' || action.kind === 'compact';
        return {
          ...s,
          model: modelFromCard !== undefined ? modelFromCard : s.model,
          messages: [...s.messages, card],
          ...(resetUsage ? { usageTotal: undefined, contextTokens: undefined, coachHint: null } : {}),
        };
      });

    case 'TODO_UPDATE':
      // One live checklist card per session — replaced in place (stable id)
      // rather than appended, so it always tracks the agent's latest plan.
      return updateSession(state, action.session, (s) => {
        const id = `todos-${action.session}`;
        const idx = s.messages.findIndex((m) => m.id === id);
        const card: ChatMessage = {
          id,
          role: 'todo',
          text: '',
          isStreaming: false,
          isError: false,
          createdAt: idx >= 0 ? s.messages[idx].createdAt : nowIso(),
          turnId: action.turnId,
          todos: action.todos,
        };
        if (idx < 0) return { ...s, messages: [...s.messages, card] };
        const messages = [...s.messages];
        messages[idx] = card;
        return { ...s, messages };
      });

    case 'SESSION_COACH':
      return updateSession(state, action.session, (s) => ({
        ...s,
        coachHint: action.hint,
      }));

    case 'DISMISS_COACH':
      return updateSession(state, action.session, (s) => ({
        ...s,
        coachHint: null,
      }));

    case 'LOAD_TRANSCRIPT': {
      return updateSession(state, action.session, (s) => {
        // Guard: never clobber a GENUINELY live streaming turn — unless forced
        // (e.g. after a terminal closes) OR the spinner is empty (WS chunks missed;
        // JSONL already has the reply and must be allowed to backfill).
        const isLiveStream = s.messages.some((m) => m.role === 'assistant' && m.isStreaming);
        if (isLiveStream && !action.force && !hasEmptyStreamingAssistant(s)) return s;

        // Rebuild user/assistant from transcript; keep ephemeral cards (coach, tools, …).
        //
        // A rebuilt bubble normally gets a fresh `tx-${i}` id — but a turn-tagged
        // assistant message ('turn-' + turnId, see ChatMessage.turnId) carries
        // `segments`/`turnMeta` that only live on the ORIGINAL message object, not
        // in the plain-text transcript. Blowing that away on every reload would
        // drop thinking blocks and the cost/latency footer.
        //
        // Match is TEXT-first, never positional: a purely positional cursor over
        // the tagged-only subset misattributes identity the moment tagged and
        // untagged assistant messages are interleaved (e.g. an old untagged
        // tx-* turn followed by a newer turn-tagged one) — the old turn would
        // consume the newer turn's tagged slot and inherit its turnId/turnMeta/
        // segments, while the newer turn falls through to a bare tx-i and loses
        // its own. Each tagged message is matched against a transcript assistant
        // turn by (trimmed) text equality and consumed at most once; a turn with
        // no text match falls back to a plain tx-i — dropping metadata for that
        // turn is acceptable, misattributing another turn's metadata is not.
        const turnTaggedAssistants = s.messages.filter(
          (m) => m.role === 'assistant' && m.id.startsWith('turn-'),
        );
        const consumedTaggedIds = new Set<string>();
        const messages = buildMessagesFromTranscript(
          s.messages,
          action.turns,
          (turn, i) => {
            if (turn.role === 'assistant') {
              const normalizedTurnText = turn.text.trim();
              const match = turnTaggedAssistants.find(
                (m) => !consumedTaggedIds.has(m.id) && m.text.trim() === normalizedTurnText,
              );
              if (match) {
                consumedTaggedIds.add(match.id);
                return match.text === turn.text
                  ? match
                  : { ...match, ...backfillMessageText(match, turn.text) };
              }
            }
            return {
              id: `tx-${i}`,
              role: turn.role,
              text: turn.text,
              isStreaming: false,
              isError: false,
              createdAt: nowIso(),
            };
          },
        );

        const idle = !s.turnRunning;
        return {
          ...s,
          messages,
          isLoadingHistory: false,
          ...(idle ? { activity: undefined, turnStartedAt: undefined } : {}),
        };
      });
    }

    case 'MERGE_TRANSCRIPT': {
      return updateSession(state, action.session, (s) => {
        let merged = mergeTranscriptIntoMessages(
          s.messages,
          action.turns,
          nextId,
          nowIso,
          // Keep spinner while bridge still runs tools after the first assistant segment.
          { keepStreaming: Boolean(s.turnRunning) },
        );
        if (!merged) return s;
        if (!s.turnRunning) {
          merged = finalizeOrphanRunningTools(merged);
        }
        const stillStreaming = merged.some((m) => m.role === 'assistant' && m.isStreaming);
        const stillTool = merged.some((m) => m.role === 'tool' && m.toolPhase === 'start');
        const idle = !s.turnRunning && !stillStreaming && !stillTool;
        return {
          ...s,
          messages: merged,
          isLoadingHistory: false,
          ...(idle ? { activity: undefined, turnStartedAt: undefined } : {}),
        };
      });
    }

    default:
      return undefined;
  }
}
