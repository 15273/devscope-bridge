/**
 * ModelPill — pick the Claude CLI model for the current session (Claude agent only).
 */
import { useEffect, useRef, useState } from 'react';
import { ChevronDown, Cpu } from 'lucide-react';
import type { Agent } from '@/shared/frames';
import {
  CLAUDE_MODEL_PRESETS,
  claudeModelGroupLabel,
  claudeModelPreset,
  type ClaudeModelGroup,
} from '@/shared/claudeModels';
import { AnchorPopover } from './AnchorPopover';

const POPOVER_CLASS =
  'overflow-hidden rounded-md border border-line bg-surface-overlay shadow-modal dark:shadow-modal-dark';

const GROUP_ORDER: ClaudeModelGroup[] = ['recommended', 'aliases', 'previous'];

export function ModelPill({
  modelId,
  agent = 'claude',
  onChange,
}: {
  modelId: string | null;
  agent?: Agent;
  onChange: (modelId: string | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const anchorRef = useRef<HTMLDivElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  const active = claudeModelPreset(modelId);
  const isDefault = !modelId;

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
        aria-label={`Model: ${active.label}`}
        className={`flex max-w-full items-center gap-1 rounded-md border px-2 py-1 text-2xs font-medium transition-colors duration-fast ease-tool ${
          isDefault
            ? 'border-line text-fg-muted hover:bg-surface-overlay hover:text-fg'
            : 'border-success/40 bg-success-subtle text-success'
        }`}
      >
        <Cpu size={12} strokeWidth={2} className="shrink-0" />
        <span className="truncate">{active.label}</span>
        <ChevronDown size={11} strokeWidth={2.25} className={`shrink-0 ${open ? 'rotate-180' : ''}`} />
      </button>

      <AnchorPopover
        anchorRef={anchorRef}
        popoverRef={popoverRef}
        open={open}
        width={300}
        minWidth={260}
        className={POPOVER_CLASS}
      >
        <p className="border-b border-line px-2.5 py-1.5 text-2xs text-fg-subtle">
          {agent === 'cursor'
            ? 'cursor-agent --model — applies on the next message.'
            : 'Same list as Claude Code /model — applies on the next message.'}
        </p>
        <div className="max-h-[min(22rem,50vh)] overflow-y-auto">
          {GROUP_ORDER.map((group) => {
            const items = CLAUDE_MODEL_PRESETS.filter((m) => m.group === group);
            if (items.length === 0) return null;
            return (
              <div key={group}>
                <p className="px-2.5 py-1.5 text-2xs font-medium uppercase tracking-wide text-fg-subtle">
                  {claudeModelGroupLabel(group)}
                </p>
                {items.map((m) => {
                  const selected = (m.id ?? null) === (modelId ?? null);
                  const showId =
                    m.id &&
                    m.group !== 'aliases' &&
                    m.label.toLowerCase() !== m.id.toLowerCase();
                  return (
                    <button
                      key={m.id ?? 'default'}
                      type="button"
                      onClick={() => {
                        onChange(m.id);
                        setOpen(false);
                      }}
                      className={`flex w-full items-start gap-2 px-2.5 py-2 text-left transition-colors duration-fast ease-tool hover:bg-surface-raised ${
                        selected ? 'bg-surface-raised' : ''
                      }`}
                    >
                      <Cpu
                        size={13}
                        strokeWidth={2}
                        className={`mt-0.5 shrink-0 ${selected ? 'text-success' : 'text-fg-subtle'}`}
                      />
                      <span className="min-w-0 flex-1">
                        <span className={`block text-xs font-medium ${selected ? 'text-fg' : 'text-fg-muted'}`}>
                          {m.label}
                        </span>
                        <span className="mt-0.5 block text-2xs leading-snug text-fg-subtle">{m.summary}</span>
                        {showId && (
                          <span className="mt-0.5 block font-mono text-2xs text-fg-subtle">{m.id}</span>
                        )}
                      </span>
                    </button>
                  );
                })}
              </div>
            );
          })}
        </div>
      </AnchorPopover>
    </div>
  );
}
