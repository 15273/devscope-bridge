import { describe, expect, it } from 'vitest';
import { resolveSessionPurpose, sessionKindFor } from './sessionKind';
import { groupSessionsForSidebar } from './sessionSidebarGroups';
import type { SessionState } from '../store/sessionStore';

function session(name: string, agent: 'claude' | 'cursor', purpose?: string): SessionState {
  return {
    name,
    agent,
    cwd: '/proj',
    purpose,
    lastUsed: '2026-06-15 10:00',
    messages: [],
    isConnected: false,
    isLoadingHistory: false,
  };
}

describe('sessionKind', () => {
  it('classifies user chats', () => {
    expect(sessionKindFor('agent')).toBe('chat');
    expect(sessionKindFor('what_mes')).toBe('chat');
  });

  it('classifies orchestrator sessions by name', () => {
    expect(resolveSessionPurpose('worker-abc')).toBe('worker');
    expect(resolveSessionPurpose('mgr-dev')).toBe('manager');
    expect(resolveSessionPurpose('mom')).toBe('orchestrator');
  });

  it('prefers stored purpose over name heuristics', () => {
    expect(sessionKindFor('custom', 'worker')).toBe('task');
  });
});

describe('groupSessionsForSidebar', () => {
  it('splits chats and tasks under the same project', () => {
    const groups = groupSessionsForSidebar([
      session('agent', 'claude'),
      session('jobright', 'cursor'),
      session('worker-1', 'claude'),
      session('mgr-dev', 'claude'),
    ]);
    expect(groups).toHaveLength(1);
    expect(groups[0].sections).toHaveLength(2);
    expect(groups[0].sections[0].kind).toBe('chat');
    expect(groups[0].sections[0].sessionCount).toBe(2);
    expect(groups[0].sections[1].kind).toBe('task');
    expect(groups[0].sections[1].sessionCount).toBe(2);
  });

  it('buckets chats by agent', () => {
    const chatSection = groupSessionsForSidebar([
      session('a', 'claude'),
      session('b', 'cursor'),
    ])[0].sections[0];
    expect(chatSection.agents.map((b) => b.agent)).toEqual(['claude', 'cursor']);
  });
});
