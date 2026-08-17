import { describe, expect, it } from 'vitest';
import type { ChatMessage } from '../store/sessionStore';
import { computePersistKey } from './persistKey';

function todoCard(status: string, content = 'Write test'): ChatMessage {
  return {
    id: 'todos-s1',
    role: 'todo',
    text: '',
    isStreaming: false,
    isError: false,
    createdAt: '2026-06-15T10:00:00.000Z',
    todos: [{ content, status, activeForm: 'Writing test' }],
  };
}

describe('computePersistKey', () => {
  it('changes when only a todo item status changes (id + text stay fixed)', () => {
    const before = computePersistKey([todoCard('in_progress')]);
    const after = computePersistKey([todoCard('completed')]);

    expect(before).not.toBe(after);
  });

  it('changes when only a todo item content changes (status stays fixed)', () => {
    const before = computePersistKey([todoCard('in_progress', 'Write test')]);
    const after = computePersistKey([todoCard('in_progress', 'Write a longer test')]);

    expect(before).not.toBe(after);
  });

  it('is stable when nothing changes', () => {
    expect(computePersistKey([todoCard('in_progress')])).toBe(computePersistKey([todoCard('in_progress')]));
  });
});
