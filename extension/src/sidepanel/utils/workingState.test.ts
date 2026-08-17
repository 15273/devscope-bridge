import { describe, expect, it } from 'vitest';
import {
  countQueuedSteering,
  deriveWorkingState,
  isTurnStuck,
  shouldWarnCompact,
  AUTO_COMPACT_THRESHOLD_TOKENS,
  STUCK_AFTER_NO_OUTPUT_MS,
} from './workingState';
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

describe('countQueuedSteering', () => {
  it('returns 0 when turn is not active', () => {
    const messages: ChatMessage[] = [
      { id: '1', role: 'user', text: 'hi', steering: true, isStreaming: false, isError: false, createdAt: '' },
    ];
    expect(countQueuedSteering(messages, false)).toBe(0);
  });
});

describe('deriveWorkingState', () => {
  it('is idle when bridge turn ended but orphan tool rows remain after cleanup path', () => {
    const session = baseSession({
      turnRunning: false,
      messages: [
        { id: 'u', role: 'user', text: 'q', isStreaming: false, isError: false, createdAt: '' },
        {
          id: 'a',
          role: 'assistant',
          text: 'done',
          isStreaming: false,
          isError: false,
          createdAt: '',
        },
      ],
    });
    expect(deriveWorkingState(session, false).isWorking).toBe(false);
  });

  it('shows working when a tool row is still running', () => {
    const session = baseSession({
      turnRunning: false,
      messages: [
        {
          id: 't',
          role: 'tool',
          text: '',
          tool: 'Skill',
          toolPhase: 'start',
          isStreaming: false,
          isError: false,
          createdAt: '',
        },
      ],
    });
    expect(deriveWorkingState(session, false).isWorking).toBe(true);
  });

  it('turnRunning → working with Stop affordance', () => {
    const ws = deriveWorkingState(baseSession({ turnRunning: true }), false);
    expect(ws.isWorking).toBe(true);
    expect(ws.showStop).toBe(true);
  });

  it('explicit awaitingKind → awaiting, not working, no Stop', () => {
    const ws = deriveWorkingState(
      baseSession({ turnRunning: true, awaitingKind: 'plan' }),
      false,
    );
    expect(ws.awaitingApproval).toBe(true);
    expect(ws.isWorking).toBe(false);
    expect(ws.showStop).toBe(false);
  });

  it('pending permission card (awaitingApproval arg) → awaiting', () => {
    const ws = deriveWorkingState(baseSession({ turnRunning: true }), true);
    expect(ws.awaitingApproval).toBe(true);
  });

  it('activity label alone no longer triggers awaiting (string matching removed)', () => {
    const ws = deriveWorkingState(
      baseSession({ turnRunning: true, activity: 'Waiting for your approval' }),
      false,
    );
    expect(ws.awaitingApproval).toBe(false);
    expect(ws.isWorking).toBe(true);
  });

  it('bridge queued_turns beats a lower local steering count while running', () => {
    const ws = deriveWorkingState(
      baseSession({ turnRunning: true, queuedTurns: 2 }),
      false,
    );
    expect(ws.queuedSteeringCount).toBe(2);
    expect(ws.statusLabel).toContain('2 turns queued');
  });

  it('bridge queued_turns ignored when the turn is not running', () => {
    const ws = deriveWorkingState(baseSession({ queuedTurns: 3 }), false);
    expect(ws.queuedSteeringCount).toBe(0);
  });

  it('bridge current_tool surfaces in the status label', () => {
    const ws = deriveWorkingState(
      baseSession({ turnRunning: true, currentTool: 'Bash' }),
      false,
    );
    expect(ws.statusLabel).toBe('Bash…');
  });
});

describe('isTurnStuck', () => {
  const now = 1_000_000_000_000;

  it('never stuck without last_output_at (old bridge)', () => {
    expect(isTurnStuck(baseSession({ turnRunning: true }), now)).toBe(false);
  });

  it('not stuck when idle', () => {
    expect(
      isTurnStuck(baseSession({ lastOutputAt: now - STUCK_AFTER_NO_OUTPUT_MS * 2 }), now),
    ).toBe(false);
  });

  it('stuck when running with stale output', () => {
    expect(
      isTurnStuck(
        baseSession({ turnRunning: true, lastOutputAt: now - STUCK_AFTER_NO_OUTPUT_MS - 1 }),
        now,
      ),
    ).toBe(true);
  });

  it('not stuck while awaiting a user decision', () => {
    expect(
      isTurnStuck(
        baseSession({
          turnRunning: true,
          awaitingKind: 'ask_user',
          lastOutputAt: now - STUCK_AFTER_NO_OUTPUT_MS * 2,
        }),
        now,
      ),
    ).toBe(false);
  });

  it('not stuck with recent output', () => {
    expect(
      isTurnStuck(baseSession({ turnRunning: true, lastOutputAt: now - 1_000 }), now),
    ).toBe(false);
  });
});

describe('shouldWarnCompact', () => {
  const warnTokens = AUTO_COMPACT_THRESHOLD_TOKENS * 0.8;

  it('quiet below the warn threshold', () => {
    expect(
      shouldWarnCompact(baseSession({ usageTotal: { tokens: warnTokens - 1, costUsd: 1 } })),
    ).toBe(false);
  });

  it('warns at the threshold', () => {
    expect(
      shouldWarnCompact(baseSession({ usageTotal: { tokens: warnTokens, costUsd: 1 } })),
    ).toBe(true);
  });

  it('respects dismissal until usage grows further', () => {
    const dismissed = baseSession({
      usageTotal: { tokens: warnTokens + 1_000, costUsd: 1 },
      compactBannerDismissedAt: warnTokens + 1_000,
    });
    expect(shouldWarnCompact(dismissed)).toBe(false);
    const grown = baseSession({
      usageTotal: { tokens: warnTokens + 60_000, costUsd: 1 },
      compactBannerDismissedAt: warnTokens + 1_000,
    });
    expect(shouldWarnCompact(grown)).toBe(true);
  });

  it('quiet while compacting', () => {
    expect(
      shouldWarnCompact(
        baseSession({ compacting: true, usageTotal: { tokens: warnTokens * 2, costUsd: 1 } }),
      ),
    ).toBe(false);
  });
});
