/**
 * sessionStore.ts — public barrel for the side-panel session store.
 *
 * Uses a single useReducer. All WS-sourced actions are session-scoped.
 * Chat history is persisted to chrome.storage.local on every mutation (per-profile
 * cache). Initial load merges with the bridge transcript so all Chrome profiles
 * see the same conversation.
 *
 * Implementation lives in sessionTypes / sessionHelpers / reduce*.ts.
 */
import { reduceLifecycle } from './reduceLifecycle';
import { reduceStream } from './reduceStream';
import { reduceTranscript } from './reduceTranscript';
import { isReliabilityAction, reduceReliability } from './reliabilityActions';
import type { StoreAction, StoreState } from './sessionTypes';

export type {
  ChatMessage,
  Role,
  SessionCoachHint,
  SessionState,
  StoreAction,
  StoreState,
  SubAgentRow,
} from './sessionTypes';
export { INITIAL_STATE } from './sessionTypes';
export {
  findPendingPermission,
  isEmptyAssistantBubble,
  sessionLooksStuckWorking,
} from './sessionHelpers';

export function storeReducer(state: StoreState, action: StoreAction): StoreState {
  if (isReliabilityAction(action)) {
    return reduceReliability(state, action);
  }
  return (
    reduceLifecycle(state, action) ??
    reduceStream(state, action) ??
    reduceTranscript(state, action) ??
    state
  );
}
