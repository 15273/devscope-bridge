/** ConfirmCreateEventDialog — mandatory gate before creating a calendar event. */
import { useState, useCallback } from 'react';
import { CalendarPlus } from 'lucide-react';
import type { EventDraft } from './useCalendar';

interface ConfirmCreateEventDialogProps {
  draft: EventDraft;
  onConfirm: () => Promise<void>;
  onCancel: () => void;
}

function formatRange(start: string, end: string): string {
  const s = new Date(start);
  const e = new Date(end);
  if (Number.isNaN(s.getTime())) return `${start} – ${end}`;
  const datePart = s.toLocaleString('he-IL', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
  });
  const timePart = `${s.toLocaleTimeString('he-IL', { hour: '2-digit', minute: '2-digit' })} – ${e.toLocaleTimeString('he-IL', { hour: '2-digit', minute: '2-digit' })}`;
  return `${datePart}, ${timePart}`;
}

export function ConfirmCreateEventDialog({
  draft,
  onConfirm,
  onCancel,
}: ConfirmCreateEventDialogProps) {
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const handleConfirm = useCallback(async () => {
    setCreating(true);
    setCreateError(null);
    try {
      await onConfirm();
    } catch (e) {
      setCreateError(e instanceof Error ? e.message : String(e));
      setCreating(false);
    }
  }, [onConfirm]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      dir="rtl"
    >
      <div className="flex w-[340px] max-w-[calc(100vw-32px)] flex-col gap-4 rounded-xl border border-line bg-surface p-5 shadow-modal">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-signal-subtle">
            <CalendarPlus size={16} className="text-signal" />
          </div>
          <div>
            <p className="text-xs font-semibold text-fg">יצירת אירוע ביומן</p>
            <p className="text-2xs text-fg-muted">{draft.summary}</p>
          </div>
        </div>

        <div className="space-y-2 rounded-md border border-line bg-surface-overlay p-3 text-xs text-fg">
          <p>{formatRange(draft.start, draft.end)}</p>
          {draft.location && <p>מיקום: {draft.location}</p>}
          {draft.attendees.length > 0 && (
            <p>מוזמנים: {draft.attendees.join(', ')}</p>
          )}
          {draft.add_google_meet && <p className="text-signal">+ Google Meet</p>}
          {draft.description && (
            <p className="whitespace-pre-wrap text-2xs text-fg-muted">{draft.description}</p>
          )}
        </div>

        <p className="text-2xs text-fg-muted">
          {draft.attendees.length > 0
            ? 'הזמנות יישלחו למייל של המוזמנים.'
            : 'האירוע יתווסף ליומן Google שלך.'}
        </p>

        {createError && (
          <p className="rounded-sm bg-danger-subtle px-2 py-1.5 text-2xs text-danger">
            שגיאה: {createError}
          </p>
        )}

        <div className="flex gap-2">
          <button
            type="button"
            disabled={creating}
            onClick={() => void handleConfirm()}
            className="flex h-9 flex-1 items-center justify-center rounded-md bg-signal text-xs font-semibold text-signal-contrast transition-colors hover:bg-signal-hover disabled:opacity-60"
          >
            {creating ? 'יוצר…' : 'אישור ויצירה'}
          </button>
          <button
            type="button"
            disabled={creating}
            onClick={onCancel}
            className="flex h-9 flex-1 items-center justify-center rounded-md border border-line bg-surface text-xs font-medium text-fg hover:bg-surface-overlay disabled:opacity-40"
          >
            ביטול
          </button>
        </div>
      </div>
    </div>
  );
}
