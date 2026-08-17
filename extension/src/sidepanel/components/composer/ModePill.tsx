/**
 * ModePill — Act / Plan / Inspect / Test with when-Claude-asks vs runs-alone copy.
 */
import { useEffect, useRef, useState } from 'react';
import { ChevronDown, Eye, FlaskConical, ListChecks, Zap } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import type { AgentMode } from '@/shared/frames';
import { MODE_PRESETS, modePreset } from '@/shared/modePresets';
import { AnchorPopover } from './AnchorPopover';

const MODE_ICONS: Record<AgentMode, LucideIcon> = {
  act: Zap,
  plan: ListChecks,
  inspect: Eye,
  test: FlaskConical,
};

const POPOVER_CLASS =
  'overflow-hidden rounded-md border border-line bg-surface-overlay shadow-modal dark:shadow-modal-dark';

export function ModePill({ mode, onChange }: { mode: AgentMode; onChange: (m: AgentMode) => void }) {
  const [open, setOpen] = useState(false);
  const anchorRef = useRef<HTMLDivElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  const active = modePreset(mode);
  const ActiveIcon = MODE_ICONS[mode];
  const isDefault = mode === 'act';

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node;
      if (anchorRef.current?.contains(t) || popoverRef.current?.contains(t)) return;
      setOpen(false);
    };
    window.addEventListener('mousedown', onDown);
    return () => window.removeEventListener('mousedown', onDown);
  }, [open]);

  return (
    <div ref={anchorRef} className="relative max-w-full">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        title={active.summary}
        className={`flex items-center gap-1 rounded-md border px-2 py-1 text-2xs font-medium transition-colors duration-fast ease-tool ${
          isDefault
            ? 'border-line text-fg-muted hover:bg-surface-overlay hover:text-fg'
            : 'border-signal/40 bg-signal-subtle text-signal'
        }`}
      >
        <ActiveIcon size={12} strokeWidth={2} />
        {active.label}
        <ChevronDown size={11} strokeWidth={2.25} className={open ? 'rotate-180' : ''} />
      </button>

      <AnchorPopover
        anchorRef={anchorRef}
        popoverRef={popoverRef}
        open={open}
        width={272}
        minWidth={240}
        className={POPOVER_CLASS}
      >
        <p className="border-b border-line px-2.5 py-1.5 text-2xs text-fg-subtle">
          Same live tab — mode only changes how Claude decides vs asks.
        </p>
        {MODE_PRESETS.map((m) => {
          const Icon = MODE_ICONS[m.id];
          const selected = m.id === mode;
          return (
            <button
              key={m.id}
              type="button"
              onClick={() => {
                onChange(m.id);
                setOpen(false);
              }}
              className={`flex w-full items-start gap-2 px-2.5 py-2 text-left transition-colors duration-fast ease-tool hover:bg-surface-raised ${
                selected ? 'bg-surface-raised' : ''
              }`}
            >
              <Icon size={13} strokeWidth={2} className={`mt-0.5 shrink-0 ${selected ? 'text-signal' : 'text-fg-subtle'}`} />
              <span className="min-w-0 flex-1">
                <span className={`block text-xs font-medium ${selected ? 'text-fg' : 'text-fg-muted'}`}>
                  {m.label}
                </span>
                <span className="mt-0.5 block text-2xs leading-snug text-fg-muted">{m.summary}</span>
                <span className="mt-1 block text-2xs leading-snug text-fg-subtle">
                  <span className="font-medium text-fg-muted">Asks:</span> {m.asksWhen}
                </span>
                <span className="mt-0.5 block text-2xs leading-snug text-fg-subtle">
                  <span className="font-medium text-fg-muted">Tools:</span> {m.permissions}
                </span>
              </span>
            </button>
          );
        })}
      </AnchorPopover>
    </div>
  );
}

/** Re-export for slash commands / tests */
export { MODE_PRESETS as MODES };
