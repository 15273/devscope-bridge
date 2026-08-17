/**
 * SchedulePanel — list recurring schedules with playbook memory indicator.
 */
import { useState } from 'react';
import { CalendarClock, ChevronLeft } from 'lucide-react';
import { parseSchedulePlaybook, type ScheduleEntry } from '../bridge';
import { ScheduleDetailPanel } from './ScheduleDetailPanel';

interface SchedulePanelProps {
  schedules: ScheduleEntry[];
  onRefresh: () => void;
  onNewSchedule: () => void;
}

function hasPlaybook(sched: ScheduleEntry): boolean {
  const pb = parseSchedulePlaybook(sched.playbook);
  return Boolean(
    pb.site || (pb.entry_urls?.length ?? 0) > 0 || (pb.workflow?.length ?? 0) > 0
    || Object.keys(pb.selectors ?? {}).length > 0 || pb.notes,
  );
}

export function SchedulePanel({ schedules, onRefresh, onNewSchedule }: SchedulePanelProps) {
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const selected = schedules.find((s) => s.id === selectedId) ?? null;

  if (selected) {
    return (
      <ScheduleDetailPanel
        schedule={selected}
        onClose={() => setSelectedId(null)}
        onSaved={() => {
          onRefresh();
          setSelectedId(null);
        }}
      />
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-hidden" dir="rtl">
      <div className="flex shrink-0 items-center justify-between gap-2 px-1">
        <p className="text-2xs text-fg-subtle">
          משימות חוזרות עם playbook — selectors ושלבים נשמרים בין ריצות
        </p>
        <button type="button" onClick={onNewSchedule}
          className="shrink-0 rounded-md bg-signal px-2.5 py-1 text-xs font-medium text-signal-contrast">
          + תזמון
        </button>
      </div>
      <ul className="min-h-0 flex-1 space-y-1.5 overflow-y-auto">
        {schedules.length === 0 ? (
          <li className="py-8 text-center text-xs text-fg-subtle">אין תזמונים עדיין</li>
        ) : (
          schedules.map((s) => (
            <li key={s.id}>
              <button type="button" onClick={() => setSelectedId(s.id)}
                className="flex w-full items-start gap-2 rounded-md border border-line/70 bg-surface-raised px-2.5 py-2 text-right hover:border-signal/40">
                <CalendarClock size={14} className="mt-0.5 shrink-0 text-fg-subtle" />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-xs font-medium text-fg">{s.title}</p>
                  <p className="mt-0.5 text-2xs text-fg-subtle">
                    הבא: {s.next_run_at ?? '—'}
                    {s.template?.domain && ` · ${s.template.domain}`}
                  </p>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {hasPlaybook(s) && (
                      <span className="rounded bg-signal/15 px-1 py-0.5 text-2xs text-signal">playbook</span>
                    )}
                    {!s.enabled && (
                      <span className="rounded bg-surface-overlay px-1 py-0.5 text-2xs text-fg-subtle">מושבת</span>
                    )}
                  </div>
                </div>
                <ChevronLeft size={14} className="shrink-0 text-fg-subtle" />
              </button>
            </li>
          ))
        )}
      </ul>
    </div>
  );
}
