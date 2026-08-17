/**
 * SessionStatusChip — centered, no-fill status chip for session lifecycle events.
 *
 * Variants:
 *  context_recovered  → "↺ Context recovered — rebuilt from transcript"
 *  interrupted        → "⏹ Interrupted"
 *  idle_evicted       → "⏸ Session idle — evicted"
 *  reconnected        → "↻ Reconnected"
 *
 * Deliberately no background fill — it reads like a timeline divider,
 * not a content bubble.
 */
import type { ChatMessage } from '../store/sessionStore';

interface SessionStatusChipProps {
  message: ChatMessage;
}

const KIND_CONFIG: Record<
  NonNullable<ChatMessage['statusKind']>,
  { icon: string; label: string; accentClass: string }
> = {
  context_recovered: {
    icon: '↺',
    label: 'Context recovered — rebuilt from transcript',
    accentClass: 'border-signal/50 text-signal',
  },
  interrupted: {
    icon: '⏹',
    label: 'Interrupted',
    accentClass: 'border-warning/50 text-warning',
  },
  idle_evicted: {
    icon: '⏸',
    label: 'Session idle — evicted',
    accentClass: 'border-line text-fg-subtle',
  },
  reconnected: {
    icon: '↻',
    label: 'Reconnected',
    accentClass: 'border-success/50 text-success',
  },
  session_command: {
    icon: '⚡',
    label: 'Session command dispatched',
    accentClass: 'border-signal/50 text-signal',
  },
  compacting: {
    icon: '📦',
    label: 'Compacting session…',
    accentClass: 'border-signal/50 text-signal',
  },
  compact_done: {
    icon: '📦',
    label: 'Session compacted',
    accentClass: 'border-success/50 text-success',
  },
  compact_failed: {
    icon: '📦',
    label: 'Compact failed — session left untouched',
    accentClass: 'border-danger/50 text-danger',
  },
  bound_tab: {
    icon: '🔗',
    label: 'Controlling tab',
    accentClass: 'border-signal/50 text-signal',
  },
};

export function SessionStatusChip({ message }: SessionStatusChipProps) {
  const kind = message.statusKind ?? 'reconnected';
  const cfg = KIND_CONFIG[kind];
  const spinning = kind === 'compacting' && message.isStreaming;

  return (
    <div className="my-2 flex flex-col items-center gap-0.5">
      <div
        className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-[11px] font-medium ${cfg.accentClass}`}
        role="status"
        aria-label={cfg.label}
      >
        {spinning ? (
          <svg
            className="h-3 w-3 animate-spin"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.5"
            aria-hidden
          >
            <path d="M21 12a9 9 0 1 1-6.219-8.56" strokeLinecap="round" />
          </svg>
        ) : (
          <span aria-hidden>{cfg.icon}</span>
        )}
        {cfg.label}
      </div>
      {message.statusDetail && (
        <p className="max-w-[90%] text-center text-2xs text-fg-subtle">{message.statusDetail}</p>
      )}
    </div>
  );
}
