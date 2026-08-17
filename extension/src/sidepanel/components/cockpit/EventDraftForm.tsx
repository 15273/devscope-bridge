/** EventDraftForm — compose a calendar event before confirm. */
import { useState, useCallback } from 'react';
import type { EventDraft } from './useCalendar';

export const EMPTY_DRAFT: EventDraft = {
  summary: '',
  start: '',
  end: '',
  description: '',
  location: '',
  attendees: [],
  add_google_meet: true,
};

interface EventDraftFormProps {
  draft: EventDraft;
  onChange: (draft: EventDraft) => void;
  onSubmit: () => void;
  disabled?: boolean;
}

function toLocalInputValue(iso: string): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso.slice(0, 16);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function fromLocalInputValue(local: string): string {
  if (!local) return '';
  return local.length === 16 ? `${local}:00` : local;
}

export function EventDraftForm({ draft, onChange, onSubmit, disabled }: EventDraftFormProps) {
  const [attendeesText, setAttendeesText] = useState(draft.attendees.join(', '));

  const patch = useCallback(
    (partial: Partial<EventDraft>) => onChange({ ...draft, ...partial }),
    [draft, onChange],
  );

  return (
    <div className="space-y-2 rounded-lg border border-line bg-surface p-3">
      <h3 className="text-2xs font-semibold uppercase tracking-wide text-fg-muted">
        אירוע חדש
      </h3>
      <input
        type="text"
        value={draft.summary}
        onChange={(e) => patch({ summary: e.target.value })}
        placeholder="כותרת"
        disabled={disabled}
        className="w-full rounded-md border border-line bg-surface-raised px-2 py-1.5 text-xs text-fg placeholder:text-fg-muted disabled:opacity-50"
      />
      <div className="grid grid-cols-2 gap-2">
        <label className="text-2xs text-fg-muted">
          התחלה
          <input
            type="datetime-local"
            value={toLocalInputValue(draft.start)}
            onChange={(e) => patch({ start: fromLocalInputValue(e.target.value) })}
            disabled={disabled}
            className="mt-0.5 w-full rounded-md border border-line bg-surface-raised px-2 py-1.5 text-xs text-fg disabled:opacity-50"
          />
        </label>
        <label className="text-2xs text-fg-muted">
          סיום
          <input
            type="datetime-local"
            value={toLocalInputValue(draft.end)}
            onChange={(e) => patch({ end: fromLocalInputValue(e.target.value) })}
            disabled={disabled}
            className="mt-0.5 w-full rounded-md border border-line bg-surface-raised px-2 py-1.5 text-xs text-fg disabled:opacity-50"
          />
        </label>
      </div>
      <input
        type="text"
        value={draft.location}
        onChange={(e) => patch({ location: e.target.value })}
        placeholder="מיקום (אופציונלי)"
        disabled={disabled}
        className="w-full rounded-md border border-line bg-surface-raised px-2 py-1.5 text-xs text-fg placeholder:text-fg-muted disabled:opacity-50"
      />
      <input
        type="text"
        value={attendeesText}
        onChange={(e) => {
          setAttendeesText(e.target.value);
          const emails = e.target.value
            .split(/[,;\s]+/)
            .map((s) => s.trim())
            .filter(Boolean);
          patch({ attendees: emails });
        }}
        placeholder="מוזמנים (מיילים, מופרדים בפסיק)"
        disabled={disabled}
        className="w-full rounded-md border border-line bg-surface-raised px-2 py-1.5 text-xs text-fg placeholder:text-fg-muted disabled:opacity-50"
      />
      <textarea
        value={draft.description}
        onChange={(e) => patch({ description: e.target.value })}
        placeholder="תיאור (אופציונלי)"
        rows={2}
        disabled={disabled}
        className="w-full resize-none rounded-md border border-line bg-surface-raised px-2 py-1.5 text-xs text-fg placeholder:text-fg-muted disabled:opacity-50"
      />
      <label className="flex items-center gap-2 text-xs text-fg">
        <input
          type="checkbox"
          checked={draft.add_google_meet}
          onChange={(e) => patch({ add_google_meet: e.target.checked })}
          disabled={disabled}
          className="rounded border-line"
        />
        הוסף Google Meet
      </label>
      <button
        type="button"
        onClick={onSubmit}
        disabled={disabled || !draft.summary.trim() || !draft.start || !draft.end}
        className="w-full rounded-md bg-signal py-2 text-xs font-semibold text-signal-contrast transition-colors hover:bg-signal-hover disabled:cursor-not-allowed disabled:opacity-50"
      >
        המשך לאישור
      </button>
    </div>
  );
}
