/**
 * ScheduleDraftCard — pinned above the composer during a schedule_setup chat.
 * Mirrors the draft as the conversation fills it in; no buttons except the
 * jump to the task's chat once the draft is committed in conversation.
 */
import { useEffect, useState } from 'react';
import { ArrowLeft, CheckCircle2, ClipboardList } from 'lucide-react';
import {
  draftIdForSession,
  fetchSetupDraft,
  type ScheduleSetupDraft,
} from '../integrations/scheduleSetup';

const DAY_NAMES = ['ראשון', 'שני', 'שלישי', 'רביעי', 'חמישי', 'שישי', 'שבת'];

export function formatRecurrence(rec: Record<string, unknown> | undefined): string | null {
  if (!rec || Object.keys(rec).length === 0) return null;
  if (typeof rec.daily_at === 'string') return `כל יום ב-${rec.daily_at}`;
  if (typeof rec.every_minutes === 'number') return `כל ${rec.every_minutes} דקות`;
  const weekly = rec.weekly_at as { day?: number; time?: string } | undefined;
  if (weekly && typeof weekly.time === 'string') {
    const day = DAY_NAMES[weekly.day ?? 0] ?? String(weekly.day);
    return `כל יום ${day} ב-${weekly.time}`;
  }
  return JSON.stringify(rec);
}

interface ScheduleDraftCardProps {
  sessionName: string;
  onOpenScheduleChat: (scheduleId: number) => void;
}

export function ScheduleDraftCard({ sessionName, onOpenScheduleChat }: ScheduleDraftCardProps) {
  const draftId = draftIdForSession(sessionName);
  const [draft, setDraft] = useState<ScheduleSetupDraft | null>(null);

  useEffect(() => {
    if (!draftId) return undefined;
    let cancelled = false;
    const load = async () => {
      const next = await fetchSetupDraft(draftId);
      if (!cancelled && next) setDraft(next);
    };
    void load();
    const timer = setInterval(() => void load(), 4_000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [draftId]);

  if (!draftId || !draft) return null;

  if (draft.status === 'committed' && draft.schedule_id) {
    return (
      <div className="mx-2.5 mb-1.5 flex items-center gap-2 rounded-lg border border-success/40 bg-success/10 px-2.5 py-2" dir="rtl">
        <CheckCircle2 size={15} className="shrink-0 text-success" />
        <p className="min-w-0 flex-1 truncate text-xs text-fg">
          המשימה "{draft.title}" נוצרה ותרוץ לפי התזמון
        </p>
        <button type="button" onClick={() => onOpenScheduleChat(draft.schedule_id!)}
          className="flex shrink-0 items-center gap-1 rounded-md bg-success px-2 py-1 text-2xs font-medium text-surface">
          לצ'אט של המשימה
          <ArrowLeft size={12} />
        </button>
      </div>
    );
  }

  const recurrence = formatRecurrence(draft.recurrence);
  return (
    <div className="mx-2.5 mb-1.5 rounded-lg border border-line bg-surface-raised px-2.5 py-2" dir="rtl">
      <div className="flex items-center gap-1.5">
        <ClipboardList size={13} className="shrink-0 text-signal" />
        <p className="min-w-0 flex-1 truncate text-xs font-medium text-fg">{draft.title}</p>
        <span className="shrink-0 text-2xs text-fg-subtle">טיוטת משימה</span>
      </div>
      <dl className="mt-1.5 grid grid-cols-2 gap-x-3 gap-y-0.5 text-2xs">
        <DraftFact label="מתי" value={recurrence} />
        <DraftFact label="מנוע" value={draft.agent} />
        <DraftFact label="הוראה" value={draft.instruction ? 'נקבעה' : null} />
        <DraftFact label="גבולות" value={draft.autonomy_policy ? snippet(draft.autonomy_policy) : null} />
      </dl>
    </div>
  );
}

function snippet(text: string): string {
  return text.length > 40 ? `${text.slice(0, 40)}…` : text;
}

function DraftFact({ label, value }: { label: string; value: string | null }) {
  return (
    <div className="flex min-w-0 gap-1">
      <dt className="shrink-0 text-fg-subtle">{label}:</dt>
      <dd className={`truncate ${value ? 'text-fg' : 'text-fg-subtle/70'}`}>
        {value ?? 'עוד לא נקבע'}
      </dd>
    </div>
  );
}
