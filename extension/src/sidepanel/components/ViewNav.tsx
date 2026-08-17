/**
 * ViewNav — top-level panel view switcher.
 *
 * Dispatches SET_VIEW to toggle between Chat / WhatsApp / Email cockpits.
 * Hebrew labels; RTL-safe flex layout.
 * Button contrast: active = bg-signal text-signal-contrast (light on dark/amber),
 * inactive = text-fg-muted bg-transparent hover:bg-surface-overlay.
 */
import type { Dispatch } from 'react';
import type { StoreAction, StoreState } from '../store/sessionStore';

interface ViewNavProps {
  view: StoreState['view'];
  dispatch: Dispatch<StoreAction>;
}

const VIEWS: { id: StoreState['view']; label: string }[] = [
  { id: 'chat',      label: "צ'אט" },
  { id: 'tasks',     label: 'משימות' },
  { id: 'whatsapp',  label: 'וואטסאפ' },
  { id: 'email',     label: 'מייל' },
  { id: 'calendar',  label: 'יומן' },
  { id: 'meta_ads',  label: 'פרסום' },
];

export function ViewNav({ view, dispatch }: ViewNavProps) {
  return (
    <div
      className="flex shrink-0 items-center gap-0.5 border-b border-line bg-surface-raised px-2 py-1.5"
      dir="rtl"
    >
      {VIEWS.map((v) => {
        const isActive = view === v.id;
        return (
          <button
            key={v.id}
            type="button"
            aria-pressed={isActive}
            onClick={() => dispatch({ type: 'SET_VIEW', view: v.id })}
            className={[
              'rounded-[5px] px-3 py-1 text-xs font-medium transition-colors duration-fast ease-tool',
              isActive
                ? 'bg-signal text-signal-contrast'
                : 'text-fg-muted hover:bg-surface-overlay hover:text-fg',
            ].join(' ')}
          >
            {v.label}
          </button>
        );
      })}
    </div>
  );
}
