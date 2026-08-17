/**
 * SessionCoachBanner — token-efficiency hints (model switch, auto-compact notice).
 */
import { Cpu, Sparkles, X } from 'lucide-react';
import type { SessionCoachHint } from '../store/sessionStore';
import { claudeModelPreset } from '@/shared/claudeModels';

interface SessionCoachBannerProps {
  hint: SessionCoachHint;
  onSwitchModel?: (modelId: string) => void;
  onCompact?: () => void;
  onDismiss: () => void;
}

export function SessionCoachBanner({
  hint,
  onSwitchModel,
  onCompact,
  onDismiss,
}: SessionCoachBannerProps) {
  const isAction = hint.level === 'action';
  const suggested = hint.suggestedModel ? claudeModelPreset(hint.suggestedModel) : null;

  return (
    <div
      className={`flex shrink-0 flex-col gap-1.5 border-b px-3 py-2 text-2xs ${
        isAction
          ? 'border-signal/40 bg-signal-subtle/60 text-fg'
          : 'border-warning/40 bg-warning-subtle/50 text-fg'
      }`}
      role="status"
    >
      <div className="flex items-start gap-2">
        <Sparkles size={13} strokeWidth={2} className="mt-0.5 shrink-0 text-signal" aria-hidden />
        <div className="min-w-0 flex-1">
          <p className="font-medium">{hint.title}</p>
          {hint.body && <p className="mt-0.5 text-fg-muted">{hint.body}</p>}
        </div>
        <button
          type="button"
          onClick={onDismiss}
          className="shrink-0 rounded-sm p-0.5 text-fg-subtle hover:bg-surface-overlay hover:text-fg"
          aria-label="Dismiss"
        >
          <X size={12} strokeWidth={2.25} />
        </button>
      </div>
      <div className="flex flex-wrap gap-1.5 pl-5">
        {suggested && onSwitchModel && (
          <button
            type="button"
            onClick={() => onSwitchModel(suggested.id)}
            className="flex items-center gap-1 rounded-sm border border-signal/40 bg-surface px-2 py-1 font-medium text-signal transition-colors hover:bg-signal-subtle"
          >
            <Cpu size={11} strokeWidth={2} />
            Switch to {suggested.label}
          </button>
        )}
        {onCompact && hint.level !== 'action' && (
          <button
            type="button"
            onClick={onCompact}
            className="rounded-sm border border-line bg-surface px-2 py-1 font-medium text-fg-muted transition-colors hover:border-signal/40 hover:text-signal"
          >
            Compact now
          </button>
        )}
      </div>
    </div>
  );
}
