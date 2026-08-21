import { describe, expect, it } from 'vitest';
import { collectPendingRecoveryTargets } from './pendingRecovery';
import type { SessionInfo } from '@/shared/frames';
import type { ChatMessage, SessionState } from '../store/sessionStore';

function baseSession(overrides: Partial<SessionState> = {}): SessionState {
  return {
    name: 'test',
    agent: 'claude',
    cwd: '/tmp',
    lastUsed: new Date().toISOString(),
    messages: [],
    isConnected: true,
    isLoadingHistory: false,
    ...overrides,
  };
}

function info(overrides: Partial<SessionInfo> = {}): SessionInfo {
  return { agent: 'claude', cwd: '/tmp', last_used: '', ...overrides } as SessionInfo;
}

function pendingCard(): ChatMessage {
  return {
    id: 'p1',
    role: 'permission',
    text: 'Allow Bash?',
    isStreaming: false,
    isError: false,
    createdAt: '',
    actionId: 'req-1',
    permKind: 'tool',
    permOptions: [{ id: 'allow', label: 'Allow' }],
  };
}

describe('collectPendingRecoveryTargets', () => {
  it('includes a session never recovered before (first sight)', () => {
    const targets = collectPendingRecoveryTargets(
      { s1: info() },
      {},
      new Set(),
    );
    expect(targets).toEqual(['s1']);
  });

  it('re-includes an already-recovered session when the bridge reports awaiting but the store has no card', () => {
    // The bug: banner says "Waiting for your approval" (server awaiting set)
    // but the card was lost (missed WS frame / store rebuild) — must re-recover.
    const targets = collectPendingRecoveryTargets(
      { s1: info({ awaiting: 'tool' }) },
      { s1: baseSession({ messages: [] }) },
      new Set(['s1']),
    );
    expect(targets).toEqual(['s1']);
  });

  it('skips an already-recovered session whose pending card is present', () => {
    const targets = collectPendingRecoveryTargets(
      { s1: info({ awaiting: 'tool' }) },
      { s1: baseSession({ messages: [pendingCard()] }) },
      new Set(['s1']),
    );
    expect(targets).toEqual([]);
  });

  it('skips an already-recovered session with nothing awaiting', () => {
    const targets = collectPendingRecoveryTargets(
      { s1: info({ awaiting: null }) },
      { s1: baseSession() },
      new Set(['s1']),
    );
    expect(targets).toEqual([]);
  });

  it('re-includes an awaiting session missing from the local store entirely', () => {
    const targets = collectPendingRecoveryTargets(
      { s1: info({ awaiting: 'ask_user' }) },
      {},
      new Set(['s1']),
    );
    expect(targets).toEqual(['s1']);
  });

  it('treats a resolved card as no card', () => {
    const resolved = { ...pendingCard(), permResolved: true };
    const targets = collectPendingRecoveryTargets(
      { s1: info({ awaiting: 'tool' }) },
      { s1: baseSession({ messages: [resolved] }) },
      new Set(['s1']),
    );
    expect(targets).toEqual(['s1']);
  });
});
