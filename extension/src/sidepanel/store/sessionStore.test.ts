import { describe, it, expect } from 'vitest';
import { storeReducer, INITIAL_STATE, type ChatMessage } from './sessionStore';
import type { TurnSegment, TurnMeta } from './turnSegments';

function sessionWithLoading(name = 'test') {
  const now = new Date().toISOString();
  return storeReducer(INITIAL_STATE, {
    type: 'SET_SESSIONS',
    infos: {
      [name]: {
        session_id: name,
        created_at: now,
        last_used: now,
        active: true,
        agent: 'claude',
        cwd: '/tmp',
        turn_running: false,
      },
    },
  });
}

describe('view routing', () => {
  it('defaults to chat', () => {
    expect(INITIAL_STATE.view).toBe('chat');
  });
  it('SET_VIEW switches the active view', () => {
    const next = storeReducer(INITIAL_STATE, { type: 'SET_VIEW', view: 'whatsapp' });
    expect(next.view).toBe('whatsapp');
  });
});

describe('history load race', () => {
  it('APPEND_USER cancels loading and keeps the optimistic bubble', () => {
    const loading = sessionWithLoading('s1');
    expect(loading.sessions.s1.isLoadingHistory).toBe(true);

    const afterSend = storeReducer(loading, {
      type: 'APPEND_USER',
      session: 's1',
      id: 'u1',
      text: 'hello',
    });
    expect(afterSend.sessions.s1.isLoadingHistory).toBe(false);
    expect(afterSend.sessions.s1.messages.some((m) => m.role === 'user' && m.text === 'hello')).toBe(
      true,
    );

    const staleHistory: ChatMessage[] = [];
    const afterStale = storeReducer(afterSend, {
      type: 'SET_HISTORY',
      name: 's1',
      messages: staleHistory,
    });
    expect(afterStale.sessions.s1.messages.some((m) => m.text === 'hello')).toBe(true);
  });

  it('SET_HISTORY applies while still loading', () => {
    const loading = sessionWithLoading('s1');
    const loaded: ChatMessage[] = [
      {
        id: 'tx-0',
        role: 'user',
        text: 'prior',
        isStreaming: false,
        isError: false,
        createdAt: new Date().toISOString(),
      },
    ];
    const next = storeReducer(loading, { type: 'SET_HISTORY', name: 's1', messages: loaded });
    expect(next.sessions.s1.isLoadingHistory).toBe(false);
    expect(next.sessions.s1.messages).toHaveLength(1);
  });

  it('SET_HISTORY force always applies (session reset)', () => {
    const base = sessionWithLoading('s1');
    const withMsg = storeReducer(base, {
      type: 'APPEND_USER',
      session: 's1',
      id: 'u1',
      text: 'keep me',
    });
    const saved = withMsg.sessions.s1.messages;

    const restored = storeReducer(withMsg, {
      type: 'SET_HISTORY',
      name: 's1',
      messages: saved,
      force: true,
    });
    expect(restored.sessions.s1.messages.some((m) => m.text === 'keep me')).toBe(true);
  });
});

describe('LOAD_TRANSCRIPT empty streaming backfill', () => {
  it('allows non-force load when the streaming bubble is empty (missed WS)', () => {
    let state = sessionWithLoading('s1');
    state = storeReducer(state, {
      type: 'SET_HISTORY',
      name: 's1',
      messages: [],
    });
    state = storeReducer(state, {
      type: 'APPEND_USER',
      session: 's1',
      id: 'u1',
      text: 'hello',
    });
    expect(state.sessions.s1.messages.some((m) => m.role === 'assistant' && m.isStreaming)).toBe(
      true,
    );

    const next = storeReducer(state, {
      type: 'LOAD_TRANSCRIPT',
      session: 's1',
      turns: [
        { role: 'user', text: 'hello' },
        { role: 'assistant', text: 'Fetched from JSONL' },
      ],
      force: false,
    });
    const assistant = next.sessions.s1.messages.find((m) => m.role === 'assistant');
    expect(assistant?.text).toBe('Fetched from JSONL');
    expect(assistant?.isStreaming).toBe(false);
    expect(next.sessions.s1.activity).toBeUndefined();
  });
});

describe('LOAD_TRANSCRIPT turn-tagged identity preservation', () => {
  it('preserves id/turnId/segments/turnMeta of a turn-tagged assistant message matched by text', () => {
    let state = sessionWithLoading('s1');
    state = storeReducer(state, { type: 'SET_HISTORY', name: 's1', messages: [] });
    state = storeReducer(state, {
      type: 'APPEND_USER',
      session: 's1',
      id: 'u1',
      text: 'hello',
    });

    const segments: TurnSegment[] = [{ kind: 'text', blockIndex: 1, text: 'Final answer' }];
    const turnMeta: TurnMeta = {
      durationMs: 1200,
      costUsd: 0.01,
      inputTokens: 10,
      outputTokens: 20,
      model: 'claude-sonnet-5',
    };
    const now = new Date().toISOString();
    const withTurnTagged: ChatMessage[] = [
      { id: 'u1', role: 'user', text: 'hello', isStreaming: false, isError: false, createdAt: now },
      {
        id: 'turn-abc',
        role: 'assistant',
        text: 'Final answer',
        isStreaming: false,
        isError: false,
        createdAt: now,
        turnId: 'abc',
        segments,
        turnMeta,
      },
    ];
    state = storeReducer(state, {
      type: 'SET_HISTORY',
      name: 's1',
      messages: withTurnTagged,
      force: true,
    });

    const next = storeReducer(state, {
      type: 'LOAD_TRANSCRIPT',
      session: 's1',
      turns: [
        { role: 'user', text: 'hello' },
        { role: 'assistant', text: 'Final answer' },
      ],
      force: false,
    });

    const assistant = next.sessions.s1.messages.find((m) => m.role === 'assistant');
    expect(assistant?.id).toBe('turn-abc');
    expect(assistant?.turnId).toBe('abc');
    expect(assistant?.segments).toEqual(segments);
    expect(assistant?.turnMeta).toEqual(turnMeta);
  });

  it('tolerates whitespace-only text differences (trim) — preserves identity and syncs text/segments', () => {
    let state = sessionWithLoading('s1');
    state = storeReducer(state, { type: 'SET_HISTORY', name: 's1', messages: [] });
    state = storeReducer(state, {
      type: 'APPEND_USER',
      session: 's1',
      id: 'u1',
      text: 'hello',
    });

    const segments: TurnSegment[] = [{ kind: 'text', blockIndex: 1, text: '  partial reply  ' }];
    const now = new Date().toISOString();
    state = storeReducer(state, {
      type: 'SET_HISTORY',
      name: 's1',
      messages: [
        { id: 'u1', role: 'user', text: 'hello', isStreaming: false, isError: false, createdAt: now },
        {
          id: 'turn-xyz',
          role: 'assistant',
          text: '  partial reply  ',
          isStreaming: false,
          isError: false,
          createdAt: now,
          turnId: 'xyz',
          segments,
        },
      ],
      force: true,
    });

    const next = storeReducer(state, {
      type: 'LOAD_TRANSCRIPT',
      session: 's1',
      turns: [
        { role: 'user', text: 'hello' },
        { role: 'assistant', text: 'partial reply' },
      ],
      force: false,
    });

    const assistant = next.sessions.s1.messages.find((m) => m.role === 'assistant');
    expect(assistant?.id).toBe('turn-xyz');
    expect(assistant?.turnId).toBe('xyz');
    // A whitespace-only difference is not a mismatch worth repairing: rebuilding
    // the segments would collapse them into one array whose entries re-key, and
    // SegmentedMessageBody keys text blocks by array position — so the bubble
    // remounts and flashes. The array must come back reference-identical.
    expect(assistant?.segments).toBe(segments);
    expect(assistant?.segments).toEqual([{ kind: 'text', blockIndex: 1, text: '  partial reply  ' }]);
    expect(assistant?.text?.trim()).toBe('partial reply');
  });

  it('falls back to a plain tx-i message (dropping metadata) when no tagged message text-matches', () => {
    let state = sessionWithLoading('s1');
    state = storeReducer(state, { type: 'SET_HISTORY', name: 's1', messages: [] });
    state = storeReducer(state, {
      type: 'APPEND_USER',
      session: 's1',
      id: 'u1',
      text: 'hello',
    });

    const segments: TurnSegment[] = [{ kind: 'text', blockIndex: 1, text: 'partial' }];
    const now = new Date().toISOString();
    state = storeReducer(state, {
      type: 'SET_HISTORY',
      name: 's1',
      messages: [
        { id: 'u1', role: 'user', text: 'hello', isStreaming: false, isError: false, createdAt: now },
        {
          id: 'turn-xyz',
          role: 'assistant',
          text: 'partial',
          isStreaming: false,
          isError: false,
          createdAt: now,
          turnId: 'xyz',
          segments,
        },
      ],
      force: true,
    });

    const next = storeReducer(state, {
      type: 'LOAD_TRANSCRIPT',
      session: 's1',
      turns: [
        { role: 'user', text: 'hello' },
        { role: 'assistant', text: 'the full final reply' },
      ],
      force: false,
    });

    const assistant = next.sessions.s1.messages.find((m) => m.role === 'assistant');
    expect(assistant?.id).not.toBe('turn-xyz');
    expect(assistant?.id).toMatch(/^tx-/);
    expect(assistant?.turnId).toBeUndefined();
    expect(assistant?.segments).toBeUndefined();
    expect(assistant?.text).toBe('the full final reply');
  });

  it('matches by TEXT not position when tagged and untagged assistant messages are interleaved', () => {
    // Regression for a bug introduced by an earlier fix: a shared positional
    // cursor over the tagged-only subset assigned the FIRST assistant turn
    // encountered (untagged "Answer A") the identity of the NEWER tagged
    // message ("Answer B"), mixing turn B's turnId/turnMeta/segments onto
    // turn A's content, while turn B itself fell through to a bare tx-i and
    // lost its own metadata. Text-matching must keep both attributions
    // correct regardless of message order.
    let state = sessionWithLoading('s1');
    state = storeReducer(state, { type: 'SET_HISTORY', name: 's1', messages: [] });
    state = storeReducer(state, {
      type: 'APPEND_USER',
      session: 's1',
      id: 'u1',
      text: 'first question',
    });

    const now = new Date().toISOString();
    const segmentsB: TurnSegment[] = [
      { kind: 'thinking', text: 'pondering…', startedAt: 0, doneAt: 1 },
      { kind: 'text', blockIndex: 1, text: 'Answer B' },
    ];
    const turnMetaB: TurnMeta = {
      durationMs: 500,
      costUsd: 0.002,
      inputTokens: 5,
      outputTokens: 8,
      model: 'claude-sonnet-5',
    };
    const existing: ChatMessage[] = [
      { id: 'u1', role: 'user', text: 'first question', isStreaming: false, isError: false, createdAt: now },
      { id: 'tx-1', role: 'assistant', text: 'Answer A', isStreaming: false, isError: false, createdAt: now },
      { id: 'u2', role: 'user', text: 'second question', isStreaming: false, isError: false, createdAt: now },
      {
        id: 'turn-b',
        role: 'assistant',
        text: 'Answer B',
        isStreaming: false,
        isError: false,
        createdAt: now,
        turnId: 'b',
        segments: segmentsB,
        turnMeta: turnMetaB,
      },
    ];
    state = storeReducer(state, { type: 'SET_HISTORY', name: 's1', messages: existing, force: true });

    const next = storeReducer(state, {
      type: 'LOAD_TRANSCRIPT',
      session: 's1',
      turns: [
        { role: 'user', text: 'first question' },
        { role: 'assistant', text: 'Answer A' },
        { role: 'user', text: 'second question' },
        { role: 'assistant', text: 'Answer B' },
      ],
      force: false,
    });

    const assistants = next.sessions.s1.messages.filter((m) => m.role === 'assistant');
    expect(assistants).toHaveLength(2);

    const a = assistants.find((m) => m.text === 'Answer A');
    expect(a?.turnId).toBeUndefined();
    expect(a?.turnMeta).toBeUndefined();
    expect(a?.segments).toBeUndefined();

    const b = assistants.find((m) => m.text === 'Answer B');
    expect(b?.id).toBe('turn-b');
    expect(b?.turnId).toBe('b');
    expect(b?.segments).toEqual(segmentsB);
    expect(b?.turnMeta).toEqual(turnMetaB);
  });
});

describe('FORCE_TURN_IDLE', () => {
  it('clears orphan Thinking + running tools when bridge is idle', () => {
    let state = sessionWithLoading('s1');
    state = storeReducer(state, { type: 'SET_HISTORY', name: 's1', messages: [] });
    state = storeReducer(state, {
      type: 'APPEND_USER',
      session: 's1',
      id: 'u1',
      text: 'hello',
    });
    state = storeReducer(state, {
      type: 'TOOL_CALL',
      session: 's1',
      activity: {
        type: 'agent_activity',
        session: 's1',
        label: 'Bash',
        tool: 'Bash',
        call_id: 'call-1',
        status: 'running',
        detail: 'sleep 60',
      },
    });
    expect(state.sessions.s1.turnStartedAt).toBeTruthy();
    expect(state.sessions.s1.messages.some((m) => m.role === 'tool' && m.toolPhase === 'start')).toBe(
      true,
    );

    const cleared = storeReducer(state, { type: 'FORCE_TURN_IDLE', session: 's1' });
    expect(cleared.sessions.s1.turnRunning).toBe(false);
    expect(cleared.sessions.s1.turnStartedAt).toBeUndefined();
    expect(cleared.sessions.s1.activity).toBeUndefined();
    expect(cleared.sessions.s1.messages.some((m) => m.isStreaming)).toBe(false);
    expect(cleared.sessions.s1.messages.some((m) => m.role === 'tool' && m.toolPhase === 'start')).toBe(
      false,
    );
  });
});

describe('turn-idle cleanup and empty assistant placeholders', () => {
  function withPlaceholder(createdAt: string, extra: Partial<ChatMessage> = {}) {
    const base = sessionWithLoading('s1');
    return storeReducer(base, {
      type: 'SET_HISTORY',
      name: 's1',
      messages: [
        { id: 'u1', role: 'user', text: 'hi', isStreaming: false, isError: false, createdAt },
        {
          id: 'a1',
          role: 'assistant',
          text: '',
          isStreaming: true,
          isError: false,
          createdAt,
          ...extra,
        },
      ],
    });
  }

  it('keeps a just-opened empty placeholder streaming when a stale poll says idle', () => {
    const state = withPlaceholder(new Date().toISOString());

    const next = storeReducer(state, { type: 'TURN_STATE', session: 's1', running: false });

    const assistant = next.sessions.s1.messages.find((m) => m.role === 'assistant');
    expect(assistant).toBeDefined();
    expect(assistant?.isStreaming).toBe(true);
  });

  it('drops an empty placeholder that never filled in, rather than freezing it empty', () => {
    const stale = new Date(Date.now() - 60_000).toISOString();
    const state = withPlaceholder(stale);

    const next = storeReducer(state, { type: 'TURN_STATE', session: 's1', running: false });

    expect(next.sessions.s1.messages.some((m) => m.role === 'assistant')).toBe(false);
    expect(next.sessions.s1.messages.some((m) => m.role === 'user')).toBe(true);
  });

  it('still finalizes a streaming bubble that has content', () => {
    const state = withPlaceholder(new Date().toISOString(), { text: 'partial answer' });

    const next = storeReducer(state, { type: 'TURN_STATE', session: 's1', running: false });

    const assistant = next.sessions.s1.messages.find((m) => m.role === 'assistant');
    expect(assistant?.isStreaming).toBe(false);
    expect(assistant?.text).toBe('partial answer');
  });

  it('still finalizes a streaming bubble whose content lives in segments', () => {
    const segments: TurnSegment[] = [{ kind: 'text', blockIndex: 0, text: 'from segments' }];
    const state = withPlaceholder(new Date().toISOString(), { segments });

    const next = storeReducer(state, { type: 'TURN_STATE', session: 's1', running: false });

    const assistant = next.sessions.s1.messages.find((m) => m.role === 'assistant');
    expect(assistant?.isStreaming).toBe(false);
    expect(assistant?.segments).toEqual(segments);
  });
});

describe('FORCE_TURN_IDLE drops empty placeholders outright', () => {
  it('removes a just-opened empty bubble instead of finalizing it empty', () => {
    let state = sessionWithLoading('s1');
    state = storeReducer(state, { type: 'SET_HISTORY', name: 's1', messages: [] });
    state = storeReducer(state, { type: 'APPEND_USER', session: 's1', id: 'u1', text: 'hello' });

    const cleared = storeReducer(state, { type: 'FORCE_TURN_IDLE', session: 's1' });

    expect(cleared.sessions.s1.messages.some((m) => m.role === 'assistant')).toBe(false);
    expect(cleared.sessions.s1.messages.some((m) => m.isStreaming)).toBe(false);
  });
});
