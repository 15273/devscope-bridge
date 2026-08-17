/**
 * MedicCard — collapsible card for MEDIC watchdog reports (role === 'medic').
 *
 * Layout:
 *  ┌─ border-left accent (phase color) ──────────────────┐
 *  │  🩺 Medic · <session> · [phase badge]               │
 *  │  <streaming prose>  ▌                               │
 *  │  ▸ diagnostics (collapsed disclosure)               │
 *  └─────────────────────────────────────────────────────┘
 *
 * Phase colors:
 *  running  → signal (amber)
 *  healthy  → success (green)
 *  issue    → danger (red)
 */
import { useState } from 'react';
import { ChevronRight, TerminalSquare } from 'lucide-react';
import type { ChatMessage } from '../store/sessionStore';
import { MarkdownMessage } from './MarkdownMessage';

interface MedicCardProps {
  message: ChatMessage;
  onOpenTerminal?: (session: string) => void;
}

function PhaseBadge({ phase }: { phase: ChatMessage['medicPhase'] }) {
  if (phase === 'running') {
    return (
      <span className="flex items-center gap-1 rounded-sm bg-signal-subtle px-1.5 py-0.5 text-[10px] font-medium text-signal">
        <span className="h-1.5 w-1.5 rounded-full bg-signal animate-cursor-pulse" aria-hidden />
        running
      </span>
    );
  }
  if (phase === 'healthy') {
    return (
      <span className="rounded-sm bg-success-subtle px-1.5 py-0.5 text-[10px] font-medium text-success">
        healthy
      </span>
    );
  }
  return (
    <span className="rounded-sm bg-danger-subtle px-1.5 py-0.5 text-[10px] font-medium text-danger">
      issue
    </span>
  );
}

function borderAccent(phase: ChatMessage['medicPhase']): string {
  if (phase === 'running') return 'border-l-signal';
  if (phase === 'healthy') return 'border-l-success';
  return 'border-l-danger';
}

function DiagnosticsDisclosure({ data }: { data: Record<string, unknown> }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-2 rounded-sm border border-line text-2xs">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-1 px-2 py-1 text-fg-muted transition-colors duration-fast ease-tool hover:text-fg"
      >
        <ChevronRight
          size={11}
          strokeWidth={2.5}
          className={`transition-transform duration-fast ease-tool ${open ? 'rotate-90' : ''}`}
          aria-hidden
        />
        diagnostics
      </button>
      {open && (
        <div className="border-t border-line px-2 py-1.5">
          <pre className="max-h-48 overflow-auto whitespace-pre-wrap font-mono text-[10px] text-fg-subtle leading-relaxed">
            {JSON.stringify(data, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}

export function MedicCard({ message, onOpenTerminal }: MedicCardProps) {
  const phase = message.medicPhase ?? 'running';
  const hasDiagnostics =
    message.medicDiagnostics && Object.keys(message.medicDiagnostics).length > 0;

  return (
    <div
      className={`my-1 rounded-md border border-line border-l-2 ${borderAccent(phase)} bg-surface-raised px-3 py-2.5`}
    >
      {/* Header */}
      <div className="mb-1.5 flex items-center gap-2">
        <span className="text-xs font-semibold text-fg-muted" aria-label="MEDIC watchdog">
          🩺 Medic
        </span>
        {message.medicTarget && (
          <span className="font-mono text-2xs text-fg-subtle">{message.medicTarget}</span>
        )}
        <PhaseBadge phase={phase} />
        {message.medicTarget && onOpenTerminal && (
          <button
            type="button"
            onClick={() => onOpenTerminal(message.medicTarget!)}
            title={`Open terminal on session "${message.medicTarget}"`}
            className="ml-auto flex items-center gap-1 rounded-sm border border-line px-1.5 py-0.5 text-[10px] font-medium text-fg-muted transition-colors duration-fast ease-tool hover:border-signal/40 hover:bg-signal-subtle hover:text-signal"
          >
            <TerminalSquare size={11} strokeWidth={2} />
            Terminal
          </button>
        )}
      </div>

      {/* Prose body */}
      {message.text ? (
        <div className="text-sm text-fg">
          <MarkdownMessage text={message.text} />
          {message.isStreaming && (
            <span
              className="ml-0.5 inline-block font-mono text-signal animate-cursor-pulse"
              aria-hidden
            >
              ▌
            </span>
          )}
        </div>
      ) : message.isStreaming ? (
        <span
          className="ml-0.5 inline-block font-mono text-signal animate-cursor-pulse"
          aria-hidden
        >
          ▌
        </span>
      ) : null}

      {/* Diagnostics disclosure (collapsed by default) */}
      {hasDiagnostics && (
        <DiagnosticsDisclosure data={message.medicDiagnostics!} />
      )}
    </div>
  );
}
