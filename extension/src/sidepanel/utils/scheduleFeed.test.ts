import { describe, expect, it } from 'vitest';
import { buildFeed, formatNextRun, presenceFor } from './scheduleFeed';
import type { ScheduleRun } from '../bridge';

function run(overrides: Partial<ScheduleRun>): ScheduleRun {
  return {
    id: 1,
    schedule_id: 5,
    task_id: 't1',
    started_at: '2026-08-22 09:00:00',
    finished_at: null,
    status: 'running',
    digest_text: null,
    question_text: null,
    question_importance: null,
    answered_by: null,
    answer_text: null,
    artifacts: [],
    log_session: 'worker-t1',
    ...overrides,
  };
}

describe('buildFeed', () => {
  it('maps success to a digest item', () => {
    const feed = buildFeed([
      run({ id: 2, status: 'success', digest_text: 'סיימתי, פרסמתי את הפוסט', finished_at: '2026-08-22 09:05:00', artifacts: ['/x/r.md'] }),
    ]);
    expect(feed).toHaveLength(1);
    expect(feed[0].kind).toBe('digest');
    expect(feed[0].text).toBe('סיימתי, פרסמתי את הפוסט');
    expect(feed[0].artifacts).toEqual(['/x/r.md']);
    expect(feed[0].at).toBe('2026-08-22 09:05:00');
  });

  it('falls back to default text when success has no digest', () => {
    const feed = buildFeed([run({ status: 'success', finished_at: '2026-08-22 09:05:00' })]);
    expect(feed[0].text).toBe('הריצה הסתיימה');
  });

  it('maps failed to a failure item', () => {
    const feed = buildFeed([run({ status: 'failed', finished_at: '2026-08-22 09:05:00' })]);
    expect(feed[0].kind).toBe('failure');
    expect(feed[0].text).toBe('הריצה נכשלה');
  });

  it('maps waiting_user to a question item', () => {
    const feed = buildFeed([run({ status: 'waiting_user', question_text: 'לפרסם?' })]);
    expect(feed[0].kind).toBe('question');
    expect(feed[0].text).toBe('לפרסם?');
  });

  it('maps running to an in-progress digest item', () => {
    const feed = buildFeed([run({ status: 'running' })]);
    expect(feed[0].kind).toBe('digest');
    expect(feed[0].text).toBe('רצה עכשיו…');
  });

  it('appends a chief_answer item after answered runs', () => {
    const feed = buildFeed([
      run({
        id: 3,
        status: 'success',
        digest_text: 'בוצע',
        finished_at: '2026-08-22 09:10:00',
        question_text: 'איזה צבע?',
        answered_by: 'chief',
        answer_text: 'כחול',
      }),
    ]);
    expect(feed).toHaveLength(2);
    expect(feed[0].kind).toBe('digest');
    expect(feed[1].kind).toBe('chief_answer');
    expect(feed[1].answered).toEqual({ by: 'chief', text: 'כחול' });
    expect(feed[1].text).toBe('איזה צבע?');
  });

  it('carries the task id for answering', () => {
    const feed = buildFeed([run({ status: 'waiting_user', question_text: 'לפרסם?', task_id: 't9' })]);
    expect(feed[0].taskId).toBe('t9');
  });

  it('keeps runs newest first', () => {
    const feed = buildFeed([
      run({ id: 9, status: 'success', digest_text: 'אחרון', finished_at: '2026-08-22 10:00:00' }),
      run({ id: 8, status: 'success', digest_text: 'ראשון', finished_at: '2026-08-22 09:00:00' }),
    ]);
    expect(feed.map((f) => f.runId)).toEqual([9, 8]);
  });
});

describe('presenceFor', () => {
  it('derives presence from the latest run', () => {
    expect(presenceFor(undefined)).toBe('never');
    expect(presenceFor(run({ status: 'success' }))).toBe('success');
    expect(presenceFor(run({ status: 'failed' }))).toBe('failed');
    expect(presenceFor(run({ status: 'waiting_user' }))).toBe('waiting');
    expect(presenceFor(run({ status: 'running' }))).toBe('running');
  });
});

describe('formatNextRun', () => {
  const now = new Date(2026, 7, 22, 8, 0); // 2026-08-22 08:00

  it('formats today, tomorrow, and later dates', () => {
    expect(formatNextRun('2026-08-22 09:00:00', now)).toBe('היום 09:00');
    expect(formatNextRun('2026-08-23 09:00:00', now)).toBe('מחר 09:00');
    expect(formatNextRun('2026-08-25 14:30:00', now)).toBe('25.8 14:30');
  });

  it('handles missing values', () => {
    expect(formatNextRun(null, now)).toBe('לא מתוזמן');
  });
});
