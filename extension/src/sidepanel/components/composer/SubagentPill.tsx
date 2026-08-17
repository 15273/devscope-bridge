/**
 * SubagentPill — pick a Claude Code subagent (--agent) for the current session.
 */
import { useEffect, useRef, useState } from 'react';
import { Bot, ChevronDown } from 'lucide-react';
import { fetchClaudeAgents, type ClaudeAgentDef } from '../../bridge';
import { AnchorPopover } from './AnchorPopover';

const POPOVER_CLASS =
  'overflow-hidden rounded-md border border-line bg-surface-overlay shadow-modal dark:shadow-modal-dark';

export function SubagentPill({
  agentSlug,
  onChange,
}: {
  agentSlug: string | null;
  onChange: (slug: string | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const [agents, setAgents] = useState<ClaudeAgentDef[]>([]);
  const [loading, setLoading] = useState(true);
  const anchorRef = useRef<HTMLDivElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  const active = agents.find((a) => a.name === agentSlug);
  const isDefault = !agentSlug;

  useEffect(() => {
    let cancelled = false;
    fetchClaudeAgents()
      .then((list) => {
        if (!cancelled) setAgents(list);
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

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

  const label = active?.name ?? (isDefault ? 'Default' : agentSlug);

  return (
    <div ref={anchorRef} className="relative max-w-full">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        title={active?.description ?? 'Claude subagent (default = main agent)'}
        aria-label={`Subagent: ${label}`}
        className={`flex max-w-full items-center gap-1 rounded-md border px-2 py-1 text-2xs font-medium transition-colors duration-fast ease-tool ${
          isDefault
            ? 'border-line text-fg-muted hover:bg-surface-overlay hover:text-fg'
            : 'border-signal/40 bg-signal-subtle text-signal'
        }`}
      >
        <Bot size={12} strokeWidth={2} className="shrink-0" />
        <span className="max-w-[8rem] truncate">{label}</span>
        <ChevronDown size={11} strokeWidth={2.25} className={`shrink-0 ${open ? 'rotate-180' : ''}`} />
      </button>

      <AnchorPopover
        anchorRef={anchorRef}
        popoverRef={popoverRef}
        open={open}
        width={320}
        minWidth={260}
        className={POPOVER_CLASS}
      >
        <p className="border-b border-line px-2.5 py-1.5 text-2xs text-fg-subtle">
          Same as <code className="font-mono">claude --agent</code> — applies on the next message.
        </p>
        <div className="max-h-[min(22rem,50vh)] overflow-y-auto">
          <button
            type="button"
            onClick={() => {
              onChange(null);
              setOpen(false);
            }}
            className={`flex w-full items-start gap-2 px-2.5 py-2 text-left transition-colors duration-fast ease-tool hover:bg-surface-raised ${
              isDefault ? 'bg-surface-raised' : ''
            }`}
          >
            <Bot size={13} strokeWidth={2} className="mt-0.5 shrink-0 text-fg-subtle" />
            <span className="min-w-0 flex-1">
              <span className="block text-xs font-medium text-fg-muted">Default agent</span>
              <span className="mt-0.5 block text-2xs leading-snug text-fg-subtle">
                General Claude Code session without a specialist subagent.
              </span>
            </span>
          </button>
          {loading && (
            <p className="px-2.5 py-2 text-2xs text-fg-subtle">Loading agents…</p>
          )}
          {!loading && agents.length === 0 && (
            <p className="px-2.5 py-2 text-2xs text-fg-subtle">No .claude/agents/*.md found.</p>
          )}
          {agents.map((a) => {
            const selected = a.name === agentSlug;
            return (
              <button
                key={a.name}
                type="button"
                onClick={() => {
                  onChange(a.name);
                  setOpen(false);
                }}
                className={`flex w-full items-start gap-2 px-2.5 py-2 text-left transition-colors duration-fast ease-tool hover:bg-surface-raised ${
                  selected ? 'bg-surface-raised' : ''
                }`}
              >
                <Bot
                  size={13}
                  strokeWidth={2}
                  className={`mt-0.5 shrink-0 ${selected ? 'text-signal' : 'text-fg-subtle'}`}
                />
                <span className="min-w-0 flex-1">
                  <span className={`block text-xs font-medium ${selected ? 'text-fg' : 'text-fg-muted'}`}>
                    {a.name}
                  </span>
                  <span className="mt-0.5 block text-2xs leading-snug text-fg-subtle line-clamp-3">
                    {a.description}
                  </span>
                </span>
              </button>
            );
          })}
        </div>
      </AnchorPopover>
    </div>
  );
}
