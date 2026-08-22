import type { ScheduleRun } from '../bridge';

export interface FeedItem {
  kind: 'digest' | 'question' | 'chief_answer' | 'failure';
  runId: number;
  taskId: string;
  at: string;
  text: string;
  artifacts: string[];
  logSession: string | null;
  answered?: { by: string; text: string };
}

/** Map schedule runs (newest first from the API) to chat-feed items. */
export function buildFeed(runs: ScheduleRun[]): FeedItem[] {
  const items: FeedItem[] = [];
  for (const run of runs) {
    const at = run.finished_at ?? run.started_at;
    const base = {
      runId: run.id,
      taskId: run.task_id,
      at,
      artifacts: run.artifacts ?? [],
      logSession: run.log_session,
    };
    if (run.status === 'waiting_user') {
      items.push({ ...base, kind: 'question', text: run.question_text ?? 'אני צריכה תשובה ממך' });
    } else if (run.status === 'failed') {
      items.push({ ...base, kind: 'failure', text: run.digest_text ?? 'הריצה נכשלה' });
    } else if (run.status === 'running') {
      items.push({ ...base, kind: 'digest', text: run.digest_text ?? 'רצה עכשיו…' });
    } else {
      items.push({ ...base, kind: 'digest', text: run.digest_text ?? 'הריצה הסתיימה' });
    }
    if (run.status !== 'waiting_user' && run.answered_by && run.question_text) {
      items.push({
        ...base,
        kind: 'chief_answer',
        text: run.question_text,
        answered: { by: run.answered_by, text: run.answer_text ?? '' },
      });
    }
  }
  return items;
}

/** Presence-style status for an employee card, derived from the latest run. */
export type SchedulePresence = 'success' | 'failed' | 'waiting' | 'running' | 'never';

export function presenceFor(latest: ScheduleRun | undefined): SchedulePresence {
  if (!latest) return 'never';
  if (latest.status === 'waiting_user') return 'waiting';
  if (latest.status === 'failed') return 'failed';
  if (latest.status === 'running') return 'running';
  return 'success';
}

/** "22.8 09:05" from a bridge timestamp — for feed bubbles. */
export function formatRunTime(at: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2})/.exec(at);
  if (!m) return at;
  const [, , mo, d, hh, mm] = m;
  return `${Number(d)}.${Number(mo)} ${hh}:${mm}`;
}

/** "היום 09:00" / "מחר 09:00" / "24.8 09:00" from a bridge timestamp. */
export function formatNextRun(nextRunAt: string | null | undefined, now: Date = new Date()): string {
  if (!nextRunAt) return 'לא מתוזמן';
  const m = /^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2})/.exec(nextRunAt);
  if (!m) return nextRunAt;
  const [, y, mo, d, hh, mm] = m;
  const target = new Date(Number(y), Number(mo) - 1, Number(d));
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const diffDays = Math.round((target.getTime() - today.getTime()) / 86_400_000);
  const time = `${hh}:${mm}`;
  if (diffDays <= 0) return `היום ${time}`;
  if (diffDays === 1) return `מחר ${time}`;
  return `${Number(d)}.${Number(mo)} ${time}`;
}
