import { describe, it, expect } from 'vitest';
import { storeReducer, INITIAL_STATE, type StoreState } from './sessionStore';

const NAME = 'test';

function withSession(): StoreState {
  const now = new Date().toISOString();
  let state = storeReducer(INITIAL_STATE, {
    type: 'SET_SESSIONS',
    infos: {
      [NAME]: {
        session_id: NAME,
        created_at: now,
        last_used: now,
        active: true,
        agent: 'claude',
        cwd: '/tmp',
        turn_running: false,
      },
    },
  });
  state = storeReducer(state, { type: 'SET_HISTORY', name: NAME, messages: [] });
  return state;
}

function messages(state: StoreState) {
  return state.sessions[NAME].messages;
}

describe('steering flush by client_msg_id (C6)', () => {
  function withTwoQueued(): StoreState {
    let state = withSession();
    state = storeReducer(state, { type: 'APPEND_USER', session: NAME, id: 'u1', text: 'first' });
    state = storeReducer(state, { type: 'CHUNK', session: NAME, text: 'reply…' });
    state = storeReducer(state, { type: 'APPEND_QUEUED', session: NAME, id: 's1', text: 'steer one' });
    state = storeReducer(state, { type: 'APPEND_QUEUED', session: NAME, id: 's2', text: 'steer two' });
    return state;
  }

  it('APPEND_QUEUED tracks ids in FIFO order', () => {
    const state = withTwoQueued();
    expect(state.sessions[NAME].steeringQueue).toEqual(['s1', 's2']);
  });

  it('flushes queued turns in order, matched by id', () => {
    let state = withTwoQueued();
    // First turn finishes; queued turn s1 starts streaming.
    state = storeReducer(state, { type: 'DONE', session: NAME });
    state = storeReducer(state, { type: 'CHUNK', session: NAME, text: 'answer to s1' });
    expect(messages(state).find((m) => m.id === 's1')?.steering).toBe(false);
    expect(messages(state).find((m) => m.id === 's2')?.steering).toBe(true);
    expect(state.sessions[NAME].steeringQueue).toEqual(['s2']);

    // Second queued turn starts.
    state = storeReducer(state, { type: 'DONE', session: NAME });
    state = storeReducer(state, { type: 'CHUNK', session: NAME, text: 'answer to s2' });
    expect(messages(state).find((m) => m.id === 's2')?.steering).toBe(false);
    expect(state.sessions[NAME].steeringQueue).toEqual([]);
  });

  it('flush survives message-array reordering (id match, not first-scan)', () => {
    let state = withTwoQueued();
    // Simulate a transcript rebuild that reordered the steering bubbles.
    const session = state.sessions[NAME];
    const reordered = [...session.messages].reverse();
    state = {
      ...state,
      sessions: { ...state.sessions, [NAME]: { ...session, messages: reordered } },
    };
    state = storeReducer(state, { type: 'DONE', session: NAME });
    state = storeReducer(state, { type: 'CHUNK', session: NAME, text: 'go' });
    // s1 (queue head) flushed even though s2 appears first in the array.
    expect(messages(state).find((m) => m.id === 's1')?.steering).toBe(false);
    expect(messages(state).find((m) => m.id === 's2')?.steering).toBe(true);
  });

  it('CANCEL_STEERING removes the bubble and its queue entry', () => {
    let state = withTwoQueued();
    state = storeReducer(state, { type: 'CANCEL_STEERING', session: NAME, messageId: 's1' });
    expect(messages(state).some((m) => m.id === 's1')).toBe(false);
    expect(state.sessions[NAME].steeringQueue).toEqual(['s2']);
  });

  it('STEERING_DROP_WARNING marks the head-of-queue bubble', () => {
    let state = withTwoQueued();
    state = storeReducer(state, { type: 'STEERING_DROP_WARNING', session: NAME });
    expect(messages(state).find((m) => m.id === 's1')?.steeringDropWarning).toBe(true);
    expect(messages(state).find((m) => m.id === 's2')?.steeringDropWarning).toBeUndefined();
  });
});

describe('MSG_DELIVERY rollback (C3)', () => {
  it('failed delivery removes the optimistic placeholder and clears Thinking…', () => {
    let state = withSession();
    state = storeReducer(state, { type: 'APPEND_USER', session: NAME, id: 'u1', text: 'hello' });
    expect(state.sessions[NAME].activity).toBe('Thinking…');
    expect(messages(state)).toHaveLength(2); // user + empty streaming assistant

    state = storeReducer(state, {
      type: 'MSG_DELIVERY',
      session: NAME,
      clientMsgId: 'u1',
      delivery: 'failed',
    });
    expect(messages(state)).toHaveLength(1);
    expect(messages(state)[0].delivery).toBe('failed');
    expect(state.sessions[NAME].activity).toBeUndefined();
    expect(state.sessions[NAME].turnStartedAt).toBeUndefined();
  });

  it('delivered ack marks the bubble without touching the placeholder', () => {
    let state = withSession();
    state = storeReducer(state, { type: 'APPEND_USER', session: NAME, id: 'u1', text: 'hello' });
    state = storeReducer(state, {
      type: 'MSG_DELIVERY',
      session: NAME,
      clientMsgId: 'u1',
      delivery: 'delivered',
    });
    expect(messages(state)[0].delivery).toBe('delivered');
    expect(messages(state)).toHaveLength(2);
  });
});

describe('liveness fields via SET_SESSIONS (contract 2)', () => {
  it('maps awaiting/current_tool/queued_turns and converts last_output_at to ms', () => {
    let state = withSession();
    const now = new Date().toISOString();
    state = storeReducer(state, {
      type: 'SET_SESSIONS',
      infos: {
        [NAME]: {
          session_id: NAME,
          created_at: now,
          last_used: now,
          active: true,
          agent: 'claude',
          cwd: '/tmp',
          turn_running: true,
          last_output_at: 1_700_000_000,
          current_tool: 'Bash',
          queued_turns: 2,
          awaiting: 'ask_user',
        },
      },
    });
    const s = state.sessions[NAME];
    expect(s.lastOutputAt).toBe(1_700_000_000_000);
    expect(s.currentTool).toBe('Bash');
    expect(s.queuedTurns).toBe(2);
    expect(s.awaitingKind).toBe('ask_user');
  });

  it('absent fields (old bridge) leave local state untouched', () => {
    let state = withSession();
    state = storeReducer(state, {
      type: 'PERMISSION_REQUEST',
      session: NAME,
      requestId: 'r1',
      kind: 'plan',
      title: 'Plan',
      description: 'd',
      options: [{ id: 'approve', label: 'Approve' }],
    });
    expect(state.sessions[NAME].awaitingKind).toBe('plan');
    const now = new Date().toISOString();
    state = storeReducer(state, {
      type: 'SET_SESSIONS',
      infos: {
        [NAME]: {
          session_id: NAME,
          created_at: now,
          last_used: now,
          active: true,
          agent: 'claude',
          cwd: '/tmp',
          turn_running: true,
        },
      },
    });
    expect(state.sessions[NAME].awaitingKind).toBe('plan');
  });
});

describe('PERMISSION_REQUEST dedupe + resolve (C4/C3)', () => {
  it('replayed request_id does not create a second card', () => {
    let state = withSession();
    const req = {
      type: 'PERMISSION_REQUEST' as const,
      session: NAME,
      requestId: 'r1',
      kind: 'plan' as const,
      title: 'Plan',
      description: 'd',
      options: [{ id: 'approve', label: 'Approve' }],
    };
    state = storeReducer(state, req);
    state = storeReducer(state, req);
    expect(messages(state).filter((m) => m.role === 'permission')).toHaveLength(1);
  });

  it('PERMISSION_RESOLVE clears awaitingKind and permDelivery', () => {
    let state = withSession();
    state = storeReducer(state, {
      type: 'PERMISSION_REQUEST',
      session: NAME,
      requestId: 'r1',
      kind: 'plan',
      title: 'Plan',
      description: 'd',
      options: [{ id: 'approve', label: 'Approve' }],
    });
    state = storeReducer(state, {
      type: 'PERM_DELIVERY',
      session: NAME,
      requestId: 'r1',
      state: 'sending',
    });
    expect(messages(state).find((m) => m.actionId === 'r1')?.permDelivery).toBe('sending');
    state = storeReducer(state, { type: 'PERMISSION_RESOLVE', session: NAME, requestId: 'r1' });
    const card = messages(state).find((m) => m.actionId === 'r1');
    expect(card?.permResolved).toBe(true);
    expect(card?.permDelivery).toBeUndefined();
    expect(state.sessions[NAME].awaitingKind).toBeNull();
  });
});

describe('COMPACT_STATE card lifecycle (C8)', () => {
  it('start opens one spinner card; done closes it in place', () => {
    let state = withSession();
    state = storeReducer(state, { type: 'COMPACT_STATE', session: NAME, phase: 'start' });
    state = storeReducer(state, { type: 'COMPACT_STATE', session: NAME, phase: 'start' });
    expect(messages(state).filter((m) => m.statusKind === 'compacting')).toHaveLength(1);
    expect(state.sessions[NAME].compacting).toBe(true);

    state = storeReducer(state, { type: 'COMPACT_STATE', session: NAME, phase: 'done' });
    expect(messages(state).filter((m) => m.statusKind === 'compacting')).toHaveLength(0);
    expect(messages(state).filter((m) => m.statusKind === 'compact_done')).toHaveLength(1);
    expect(state.sessions[NAME].compacting).toBe(false);
  });

  it('failed compact renders the failure chip', () => {
    let state = withSession();
    state = storeReducer(state, { type: 'COMPACT_STATE', session: NAME, phase: 'start' });
    state = storeReducer(state, {
      type: 'COMPACT_STATE',
      session: NAME,
      phase: 'failed',
      detail: 'summarizer timeout',
    });
    const chip = messages(state).find((m) => m.statusKind === 'compact_failed');
    expect(chip?.statusDetail).toBe('summarizer timeout');
  });
});
