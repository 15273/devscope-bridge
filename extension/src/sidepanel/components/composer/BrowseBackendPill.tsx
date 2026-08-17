/**
 * BrowseBackendPill — same browser, different driver (extension vs CDP vs auto).
 */
import { useEffect, useRef, useState } from 'react';
import { ChevronDown, Globe, MousePointer2, Sparkles } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import type { BrowseBackend } from '@/shared/browseBackend';
import { BROWSE_BACKENDS, browseBackendInfo } from '@/shared/browseBackend';
import { AnchorPopover } from './AnchorPopover';

const BACKEND_ICONS: Record<BrowseBackend, LucideIcon> = {
  extension: Globe,
  cdp: MousePointer2,
  auto: Sparkles,
};

const POPOVER_CLASS =
  'overflow-hidden rounded-md border border-line bg-surface-overlay shadow-modal dark:shadow-modal-dark';

export function BrowseBackendPill({
  backend,
  onChange,
}: {
  backend: BrowseBackend;
  onChange: (b: BrowseBackend) => void;
}) {
  const [open, setOpen] = useState(false);
  const anchorRef = useRef<HTMLDivElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  const active = browseBackendInfo(backend);
  const Icon = BACKEND_ICONS[backend];
  const isDefault = backend === 'auto';

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
        title={`Browse: ${active.summary}`}
        className={`flex items-center gap-1 rounded-md border px-2 py-1 text-2xs font-medium transition-colors duration-fast ease-tool ${
          isDefault
            ? 'border-line text-fg-muted hover:bg-surface-overlay hover:text-fg'
            : 'border-line bg-surface-raised text-fg-muted'
        }`}
      >
        <Icon size={12} strokeWidth={2} />
        {active.label}
        <ChevronDown size={11} strokeWidth={2.25} className={open ? 'rotate-180' : ''} />
      </button>

      <AnchorPopover
        anchorRef={anchorRef}
        popoverRef={popoverRef}
        open={open}
        width={256}
        minWidth={224}
        className={POPOVER_CLASS}
      >
        <p className="border-b border-line px-2.5 py-1.5 text-2xs text-fg-subtle">
          Always your open Chrome tab — never a separate Playwright browser.
        </p>
        {BROWSE_BACKENDS.map((b) => {
          const BIcon = BACKEND_ICONS[b.id];
          const selected = b.id === backend;
          return (
            <button
              key={b.id}
              type="button"
              onClick={() => {
                onChange(b.id);
                setOpen(false);
              }}
              className={`flex w-full items-start gap-2 px-2.5 py-2 text-left transition-colors duration-fast ease-tool hover:bg-surface-raised ${
                selected ? 'bg-surface-raised' : ''
              }`}
            >
              <BIcon size={13} strokeWidth={2} className={`mt-0.5 shrink-0 ${selected ? 'text-signal' : 'text-fg-subtle'}`} />
              <span className="min-w-0 flex-1">
                <span className={`block text-xs font-medium ${selected ? 'text-fg' : 'text-fg-muted'}`}>
                  {b.label}
                </span>
                <span className="mt-0.5 block text-2xs leading-snug text-fg-subtle">{b.summary}</span>
              </span>
            </button>
          );
        })}
      </AnchorPopover>
    </div>
  );
}
