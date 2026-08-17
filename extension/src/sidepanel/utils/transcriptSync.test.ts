import { describe, expect, it } from 'vitest';
import type { ChatMessage } from '../store/sessionStore';
import {
  mergeTranscriptIntoMessages,
  transcriptAheadOfUi,
  hasEmptyStreamingAssistant,
  buildMessagesFromTranscript,
  backfillMessageText,
} from './transcriptSync';
import type { SessionState } from '../store/sessionStore';
import type { TurnSegment } from '../store/turnSegments';

function assistant(text: string, streaming = false): ChatMessage {
  return {
    id: `a-${text.slice(0, 4)}`,
    role: 'assistant',
    text,
    isStreaming: streaming,
    isError: false,
    createdAt: '2026-06-15T10:00:00.000Z',
  };
}

function user(text: string): ChatMessage {
  return {
    id: `u-${text.slice(0, 4)}`,
    role: 'user',
    text,
    isStreaming: false,
    isError: false,
    createdAt: '2026-06-15T10:00:00.000Z',
  };
}

function session(messages: ChatMessage[]): SessionState {
  return {
    name: 'test',
    agent: 'cursor',
    cwd: '/proj',
    lastUsed: '2026-06-15 10:00',
    messages,
    isConnected: true,
    isLoadingHistory: false,
  };
}

describe('mergeTranscriptIntoMessages', () => {
  it('does not backfill a fresh empty assistant bubble with the previous transcript turn', () => {
    const messages = [user('hello'), assistant('old answer'), user('new question'), assistant('', true)];
    const turns = [
      { role: 'user' as const, text: 'hello' },
      { role: 'assistant' as const, text: 'old answer' },
      { role: 'user' as const, text: 'new question' },
    ];

    expect(
      mergeTranscriptIntoMessages(messages, turns, () => 'id', () => '2026-06-15T10:00:00.000Z'),
    ).toBeNull();
    expect(transcriptAheadOfUi(session(messages), turns)).toBe(false);
  });

  it('fills an empty streaming bubble when the transcript already has the reply', () => {
    const messages = [user('hello'), assistant('', true)];
    const turns = [
      { role: 'user' as const, text: 'hello' },
      { role: 'assistant' as const, text: 'Here is my answer' },
    ];

    expect(transcriptAheadOfUi(session(messages), turns)).toBe(true);
    const merged = mergeTranscriptIntoMessages(
      messages,
      turns,
      () => 'id-2',
      () => '2026-06-15T10:00:01.000Z',
    );
    expect(merged?.[1]).toMatchObject({
      role: 'assistant',
      text: 'Here is my answer',
      isStreaming: false,
    });
  });

  it('keeps streaming when keepStreaming is set (turn still running)', () => {
    const messages = [user('hello'), assistant('', true)];
    const turns = [
      { role: 'user' as const, text: 'hello' },
      { role: 'assistant' as const, text: 'Partial…' },
    ];
    const merged = mergeTranscriptIntoMessages(
      messages,
      turns,
      () => 'id-3',
      () => '2026-06-15T10:00:01.000Z',
      { keepStreaming: true },
    );
    expect(merged?.[1]).toMatchObject({
      text: 'Partial…',
      isStreaming: true,
    });
  });

  it('rebuilds segments (not just text) when backfilling a turn-tagged bubble, keeping thinking segments', () => {
    const segments: TurnSegment[] = [
      { kind: 'thinking', text: 'pondering…', startedAt: 0, doneAt: 5 },
      { kind: 'text', blockIndex: 0, text: 'old' },
    ];
    const messages: ChatMessage[] = [
      user('hello'),
      { ...assistant('old', false), segments },
    ];
    const turns = [
      { role: 'user' as const, text: 'hello' },
      { role: 'assistant' as const, text: 'new full reply' },
    ];

    const merged = mergeTranscriptIntoMessages(
      messages,
      turns,
      () => 'id-4',
      () => '2026-06-15T10:00:02.000Z',
    );

    expect(merged).not.toBeNull();
    const updated = merged?.[1];
    expect(updated?.text).toBe('new full reply');
    expect(updated?.segments).toEqual([
      { kind: 'thinking', text: 'pondering…', startedAt: 0, doneAt: 5 },
      { kind: 'text', blockIndex: 0, text: 'new full reply' },
    ]);
  });
});

function todoCard(sessionName: string): ChatMessage {
  return {
    id: `todos-${sessionName}`,
    role: 'todo',
    text: '',
    isStreaming: false,
    isError: false,
    createdAt: '2026-06-15T10:00:00.000Z',
    todos: [{ content: 'Write test', status: 'in_progress', activeForm: 'Writing test' }],
  };
}

describe('buildMessagesFromTranscript', () => {
  it('preserves a role:todo message alongside rebuilt transcript turns', () => {
    const existing = [user('hello'), todoCard('s1'), assistant('old answer')];
    const turns = [
      { role: 'user' as const, text: 'hello' },
      { role: 'assistant' as const, text: 'old answer' },
    ];

    const rebuilt = buildMessagesFromTranscript(existing, turns, (turn, i) => ({
      id: `t-${i}`,
      role: turn.role,
      text: turn.text,
      isStreaming: false,
      isError: false,
      createdAt: '2026-06-15T10:00:01.000Z',
    }));

    const preserved = rebuilt.find((m) => m.id === 'todos-s1');
    expect(preserved).toBeDefined();
    expect(preserved?.role).toBe('todo');
    expect(preserved?.todos).toEqual([
      { content: 'Write test', status: 'in_progress', activeForm: 'Writing test' },
    ]);
  });
});

describe('hasEmptyStreamingAssistant', () => {
  it('detects empty streaming bubbles', () => {
    expect(hasEmptyStreamingAssistant(session([user('hi'), assistant('', true)]))).toBe(true);
    expect(hasEmptyStreamingAssistant(session([user('hi'), assistant('done', true)]))).toBe(false);
    expect(hasEmptyStreamingAssistant(session([user('hi'), assistant('done', false)]))).toBe(false);
  });
});

describe('backfillMessageText segment stability', () => {
  const twoBlocks: TurnSegment[] = [
    { kind: 'thinking', text: 'hmm', startedAt: 1, doneAt: 2 },
    { kind: 'text', blockIndex: 0, text: 'part one' },
    { kind: 'text', blockIndex: 1, text: 'part two' },
  ];

  it('keeps the exact same segments array when the transcript agrees', () => {
    const out = backfillMessageText({ segments: twoBlocks }, 'part one\n\npart two');

    expect(out.segments).toBe(twoBlocks);
    expect(out.text).toBe('part one\n\npart two');
  });

  it('keeps segments when the transcript differs only by surrounding whitespace', () => {
    const out = backfillMessageText({ segments: twoBlocks }, '\npart one\n\npart two\n');

    expect(out.segments).toBe(twoBlocks);
  });

  it('still repairs a real mismatch by collapsing text into one segment', () => {
    const out = backfillMessageText({ segments: twoBlocks }, 'part one\n\npart two\n\npart three');

    expect(out.segments).not.toBe(twoBlocks);
    expect(out.segments).toEqual([
      { kind: 'thinking', text: 'hmm', startedAt: 1, doneAt: 2 },
      { kind: 'text', blockIndex: 0, text: 'part one\n\npart two\n\npart three' },
    ]);
    expect(out.text).toBe('part one\n\npart two\n\npart three');
  });

  it('backfills plain text for a message that has no segments', () => {
    expect(backfillMessageText({ segments: undefined }, 'hello')).toEqual({ text: 'hello' });
  });
});
