import { describe, expect, it } from 'vitest';
import { upsertToolCallRow } from './toolActivityReducer';
import type { AgentActivity } from '@/shared/frames';
import type { ChatMessage } from './sessionStore';

const helpers = {
  nextId: () => 'generated-id',
  nowIso: () => '2026-07-01T00:00:00.000Z',
};

function activity(overrides: Partial<AgentActivity>): AgentActivity {
  return {
    type: 'agent_activity',
    session: 's1',
    label: 'Browser · Navigate',
    tool: 'mcp__browser-control__browser_navigate',
    detail: 'https://example.com',
    call_id: 'call-1',
    status: 'running',
    ...overrides,
  };
}

describe('upsertToolCallRow', () => {
  it('inserts exactly one new role:"tool" row on a running activity', () => {
    const result = upsertToolCallRow([], activity({ status: 'running' }), helpers);
    expect(result).toHaveLength(1);
    expect(result[0].role).toBe('tool');
    expect(result[0].actionId).toBe('call-1');
    expect(result[0].toolPhase).toBe('start');
  });

  it('updates the same row in place when a done activity shares the call_id', () => {
    const running = upsertToolCallRow([], activity({ status: 'running' }), helpers);
    const done = upsertToolCallRow(
      running,
      activity({ status: 'done', label: 'Browser · Navigate — done', detail: 'loaded' }),
      helpers,
    );

    expect(done).toHaveLength(1);
    expect(done[0].id).toBe(running[0].id);
    expect(done[0].toolPhase).toBe('done');
    expect(done[0].toolOk).toBe(true);
    expect(done[0].isError).toBe(false);
    expect(done[0].toolLabel).toBe('Browser · Navigate');
  });

  it('updates the same row in place and marks it as an error for a matching error activity', () => {
    const running = upsertToolCallRow([], activity({ status: 'running' }), helpers);
    const errored = upsertToolCallRow(running, activity({ status: 'error', detail: 'timeout' }), helpers);

    expect(errored).toHaveLength(1);
    expect(errored[0].toolPhase).toBe('done');
    expect(errored[0].toolOk).toBe(false);
    expect(errored[0].isError).toBe(true);
  });

  it('inserts a done row directly when no running row was ever seen (history backfill race)', () => {
    const result = upsertToolCallRow([], activity({ status: 'done' }), helpers);
    expect(result).toHaveLength(1);
    expect(result[0].toolPhase).toBe('done');
  });

  it('is a no-op for a second running activity with the same call_id already tracked', () => {
    const running = upsertToolCallRow([], activity({ status: 'running' }), helpers);
    const again = upsertToolCallRow(running, activity({ status: 'running' }), helpers);
    expect(again).toHaveLength(1);
    expect(again).toEqual(running);
  });

  it('returns the messages unchanged for an activity with call_id == null (ambient ACTIVITY, not a tool call)', () => {
    const msgs: ChatMessage[] = [];
    const result = upsertToolCallRow(msgs, activity({ call_id: null, status: null }), helpers);
    expect(result).toBe(msgs);
  });

  it('inserts the tool row before a trailing streaming assistant bubble', () => {
    const streamingAssistant: ChatMessage = {
      id: 'assistant-1',
      role: 'assistant',
      text: 'partial reply...',
      isStreaming: true,
      isError: false,
      createdAt: '2026-07-01T00:00:00.000Z',
    };
    const result = upsertToolCallRow([streamingAssistant], activity({ status: 'running' }), helpers);

    expect(result).toHaveLength(2);
    expect(result[0].role).toBe('tool');
    expect(result[1]).toBe(streamingAssistant);
  });
});
