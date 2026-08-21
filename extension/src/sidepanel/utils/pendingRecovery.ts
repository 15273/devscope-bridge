/**
 * pendingRecovery.ts — which sessions need a GET /sessions/{name}/pending fetch.
 *
 * The "Waiting for your approval" banner derives from the bridge's `awaiting`
 * field (/sessions poll), while the card itself arrives on a separate WS frame.
 * If that frame is missed (socket closed, panel rebuilt the store from the
 * JSONL transcript — permission cards are ephemeral and not in it), the banner
 * shows with no card to answer. Recovery must therefore re-run whenever the
 * bridge says a decision is pending but the local store has no unresolved card,
 * not only on first sight of the session.
 */
import type { SessionInfo } from '@/shared/frames';
import type { SessionState } from '../store/sessionTypes';
import { findPendingPermission } from '../store/sessionHelpers';

export function collectPendingRecoveryTargets(
  infos: Record<string, SessionInfo>,
  sessions: Record<string, SessionState>,
  alreadyRecovered: ReadonlySet<string>,
): string[] {
  const targets: string[] = [];
  for (const [name, sessionInfo] of Object.entries(infos)) {
    if (!alreadyRecovered.has(name)) {
      targets.push(name);
      continue;
    }
    if (!sessionInfo.awaiting) continue;
    const session = sessions[name];
    if (!session || !findPendingPermission(session.messages)) {
      targets.push(name);
    }
  }
  return targets;
}
