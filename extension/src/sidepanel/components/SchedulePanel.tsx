/**
 * SchedulePanel — the "employees" list: each recurring task is a colleague card
 * with a presence dot, next-run line, and its last report's first line.
 */
import { useEffect, useState } from 'react';
import { ChevronLeft } from 'lucide-react';
import { fetchScheduleRuns, type ScheduleEntry, type ScheduleRun } from '../bridge';
import { formatNextRun, presenceFor, type SchedulePresence } from '../utils/scheduleFeed';
import { ScheduleChatPanel } from './ScheduleChatPanel';

interface SchedulePanelProps {
  schedules: ScheduleEntry[];
  onRefresh: () => void;
  onNewSchedule: () => void;
  onOpenSession: (sessionName: string) => void;
  focusScheduleId?: number | null;
  onFocusHandled?: () => void;
}

const PRESENCE_DOT: Record<SchedulePresence, string> = {
  success: 'bg-success',
  failed: 'bg-danger',
  waiting: 'bg-warning',
  running: 'bg-signal animate-pulse',
  never: 'bg-fg-subtle/50',
};

export function SchedulePanel({
  schedules, onRefresh, onNewSchedule, onOpenSession, focusScheduleId, onFocusHandled,
}: SchedulePanelProps) {
  const [selectedId, setSelectedId] = useState<number | null>(null);

  useEffect(() => {
    if (focusScheduleId != null) {
      setSelectedId(focusScheduleId);
      onFocusHandled?.();
    }
  }, [focusScheduleId, onFocusHandled]);

  const [latestRuns, setLatestRuns] = useState<Record<number, ScheduleRun | undefined>>({});
  const selected = schedules.find((s) => s.id === selectedId) ?? null;

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const entries = await Promise.all(
        schedules.map(async (s) => [s.id, (await fetchScheduleRuns(s.id))[0]] as const),
      );
      if (!cancelled) setLatestRuns(Object.fromEntries(entries));
    })();
    return () => { cancelled = true; };
  }, [schedules]);

  if (selected) {
    return (
      <ScheduleChatPanel
        schedule={selected}
        onClose={() => setSelectedId(null)}
        onRefresh={onRefresh}
        onOpenSession={onOpenSession}
      />
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-hidden" dir="rtl">
      <div className="flex shrink-0 items-center justify-between gap-2 px-1">
        <p className="text-2xs text-fg-subtle">
          כל משימה חוזרת היא עובד — עם צ'אט, זיכרון ודוחות משלה
        </p>
        <button type="button" onClick={onNewSchedule}
          className="shrink-0 rounded-md bg-signal px-2.5 py-1 text-xs font-medium text-signal-contrast">
          + משימה חדשה
        </button>
      </div>
      <ul className="min-h-0 flex-1 space-y-1.5 overflow-y-auto">
        {schedules.length === 0 ? (
          <li className="py-8 text-center text-xs text-fg-subtle">
            אין עדיין משימות חוזרות — צור אחת בשיחה
          </li>
        ) : (
          schedules.map((s) => {
            const latest = latestRuns[s.id];
            const presence = presenceFor(latest);
            const digestLine = latest?.digest_text?.split('\n')[0];
            return (
              <li key={s.id}>
                <button type="button" onClick={() => setSelectedId(s.id)}
                  className="flex w-full items-start gap-2 rounded-md border border-line/70 bg-surface-raised px-2.5 py-2 text-right hover:border-signal/40">
                  <span className={`mt-1 h-2 w-2 shrink-0 rounded-full ${PRESENCE_DOT[presence]}`} />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-xs font-medium text-fg">{s.title}</p>
                    <p className="mt-0.5 text-2xs text-fg-subtle">
                      {s.enabled === false || s.enabled === 0
                        ? 'מושהית'
                        : `הריצה הבאה: ${formatNextRun(s.next_run_at)}`}
                    </p>
                    {presence === 'waiting' && latest?.question_text ? (
                      <p className="mt-0.5 truncate text-2xs text-warning">
                        מחכה לתשובה: {latest.question_text}
                      </p>
                    ) : digestLine ? (
                      <p className="mt-0.5 truncate text-2xs text-fg-muted">{digestLine}</p>
                    ) : null}
                  </div>
                  <ChevronLeft size={14} className="mt-0.5 shrink-0 text-fg-subtle" />
                </button>
              </li>
            );
          })
        )}
      </ul>
    </div>
  );
}
