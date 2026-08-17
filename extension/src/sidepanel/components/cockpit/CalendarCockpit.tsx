/**
 * CalendarCockpit — agenda, free slots, and event creation (Phase 2).
 */
import { useState, useCallback } from 'react';
import { RefreshCw, Calendar, Clock, Plus } from 'lucide-react';
import { useCalendar, type EventDraft } from './useCalendar';
import { EventDraftForm, EMPTY_DRAFT } from './EventDraftForm';
import { ConfirmCreateEventDialog } from './ConfirmCreateEventDialog';

function formatWhen(start: string, allDay: boolean): string {
  if (allDay) return 'כל היום';
  const d = new Date(start);
  if (Number.isNaN(d.getTime())) return start;
  return d.toLocaleString('he-IL', {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function CalendarCockpit() {
  const {
    events,
    freeSlots,
    health,
    loading,
    error,
    refreshEvents,
    loadFreeSlots,
    validateDraft,
    createEvent,
  } = useCalendar();

  const [showForm, setShowForm] = useState(false);
  const [draft, setDraft] = useState<EventDraft>(EMPTY_DRAFT);
  const [pendingConfirm, setPendingConfirm] = useState<EventDraft | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  const needsAuth = health && !health.token_configured;
  const needsWriteScope = health?.token_configured && health.can_write === false;

  const openDraftFromSlot = useCallback((slot: { start: string; end: string }) => {
    setDraft({
      ...EMPTY_DRAFT,
      start: slot.start,
      end: slot.end,
    });
    setShowForm(true);
    setFormError(null);
  }, []);

  const handleReviewDraft = useCallback(async () => {
    setFormError(null);
    try {
      await validateDraft(draft);
      setPendingConfirm(draft);
    } catch (e) {
      setFormError(e instanceof Error ? e.message : String(e));
    }
  }, [draft, validateDraft]);

  const handleConfirmCreate = useCallback(async () => {
    if (!pendingConfirm) return;
    await createEvent(pendingConfirm);
    setPendingConfirm(null);
    setShowForm(false);
    setDraft(EMPTY_DRAFT);
  }, [pendingConfirm, createEvent]);

  return (
    <div dir="rtl" className="flex min-h-0 flex-1 flex-col overflow-hidden">
      <div className="flex shrink-0 items-center justify-between border-b border-line bg-surface-raised px-3 py-2">
        <div className="flex items-center gap-2 text-sm font-semibold text-fg">
          <Calendar size={16} className="text-signal" />
          יומן
        </div>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => {
              setShowForm((v) => !v);
              setFormError(null);
            }}
            disabled={needsAuth || needsWriteScope}
            className="flex h-7 items-center gap-1 rounded-md px-2 text-2xs font-medium text-signal transition-colors hover:bg-signal-subtle disabled:opacity-50"
          >
            <Plus size={12} />
            חדש
          </button>
          <button
            type="button"
            onClick={() => void refreshEvents()}
            className="flex h-7 w-7 items-center justify-center rounded-md text-fg-muted transition-colors hover:bg-surface-overlay hover:text-fg"
            aria-label="רענן"
          >
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          </button>
        </div>
      </div>

      {needsAuth && (
        <div className="mx-3 mt-3 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-fg">
          חיבור Google Calendar נדרש. הרץ:
          <code className="mt-1 block break-all rounded bg-surface px-2 py-1 text-2xs">
            python -m devscope_bridge.calendar.authorize_calendar
          </code>
        </div>
      )}

      {needsWriteScope && (
        <div className="mx-3 mt-3 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-fg">
          ליצירת אירועים — הרץ מחדש authorize_calendar (scope כולל calendar.events).
        </div>
      )}

      {(error || formError) && (
        <div className="mx-3 mt-3 rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-200">
          {formError ?? error}
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3">
        {showForm && (
          <div className="mb-4">
            <EventDraftForm
              draft={draft}
              onChange={setDraft}
              onSubmit={() => void handleReviewDraft()}
              disabled={needsAuth || needsWriteScope}
            />
          </div>
        )}

        <h3 className="mb-2 text-2xs font-semibold uppercase tracking-wide text-fg-muted">
          7 הימים הקרובים
        </h3>

        {loading && events.length === 0 ? (
          <p className="text-xs text-fg-muted">טוען אירועים…</p>
        ) : events.length === 0 ? (
          <p className="text-xs text-fg-muted">אין אירועים קרובים.</p>
        ) : (
          <ul className="space-y-2">
            {events.map((ev) => (
              <li
                key={ev.id}
                className="rounded-lg border border-line bg-surface px-3 py-2"
              >
                <div className="text-xs font-semibold text-fg">{ev.summary}</div>
                <div className="mt-0.5 text-2xs text-fg-muted">
                  {formatWhen(ev.start, ev.all_day)}
                  {ev.location ? ` · ${ev.location}` : ''}
                </div>
                {ev.meet_link && (
                  <a
                    href={ev.meet_link}
                    target="_blank"
                    rel="noreferrer"
                    className="mt-1 inline-block text-2xs text-signal hover:underline"
                  >
                    Google Meet
                  </a>
                )}
              </li>
            ))}
          </ul>
        )}

        <div className="mt-5 border-t border-line pt-4">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="flex items-center gap-1.5 text-2xs font-semibold uppercase tracking-wide text-fg-muted">
              <Clock size={12} />
              זמנים פנויים
            </h3>
            <button
              type="button"
              onClick={() => void loadFreeSlots()}
              disabled={needsAuth}
              className="rounded-md bg-surface-overlay px-2 py-1 text-2xs font-medium text-fg transition-colors hover:bg-signal-subtle hover:text-signal disabled:opacity-50"
            >
              חפש
            </button>
          </div>
          {freeSlots.length === 0 ? (
            <p className="text-2xs text-fg-muted">לחץ חפש למציאת חלונות פנויים (30 דק׳).</p>
          ) : (
            <ul className="space-y-1.5">
              {freeSlots.map((slot) => (
                <li key={slot.start}>
                  <button
                    type="button"
                    onClick={() => openDraftFromSlot(slot)}
                    disabled={needsWriteScope}
                    className="w-full rounded-md border border-line bg-surface-raised px-2 py-1.5 text-start text-xs text-fg transition-colors hover:border-signal/40 hover:bg-signal-subtle disabled:opacity-50"
                  >
                    {formatWhen(slot.start, false)}
                    <span className="ms-2 text-2xs text-fg-muted">+ צור אירוע</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      {pendingConfirm && (
        <ConfirmCreateEventDialog
          draft={pendingConfirm}
          onConfirm={handleConfirmCreate}
          onCancel={() => setPendingConfirm(null)}
        />
      )}
    </div>
  );
}
