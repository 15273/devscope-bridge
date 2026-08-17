/**
 * PermissionCard — plan approval, AskUserQuestion, and tool-blocked decisions.
 *
 * A decision flips to "Decision sent" only after the bridge acks it (perm_ack,
 * contract 1). While in flight the card shows "Sending…"; when the ack never
 * arrives the card is restored with an error note so the user can retry.
 */
import { AlertCircle, Check, ListChecks } from 'lucide-react';
import type { ChatMessage } from '../store/sessionStore';
import { AskUserCard } from './AskUserCard';
import { MarkdownMessage } from './MarkdownMessage';

/** Delivery note under the option buttons (perm_ack flow). */
function DeliveryNote({ state }: { state: ChatMessage['permDelivery'] }) {
  if (state === 'sending') {
    return (
      <p className="mt-1.5 flex items-center gap-1.5 text-2xs text-fg-muted" role="status">
        <svg className="h-3 w-3 animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" aria-hidden>
          <path d="M21 12a9 9 0 1 1-6.219-8.56" strokeLinecap="round" />
        </svg>
        Sending decision…
      </p>
    );
  }
  if (state === 'failed') {
    return (
      <p className="mt-1.5 flex items-center gap-1.5 text-2xs text-danger" role="alert">
        <AlertCircle size={12} strokeWidth={2} aria-hidden />
        Decision didn&apos;t reach the agent — try again.
      </p>
    );
  }
  return null;
}

export type PermissionRespondFn = (
  sessionName: string,
  requestId: string,
  optionId: string,
  extras?: { answers?: Record<string, string | string[]>; custom_text?: string },
) => void;

interface PermissionCardProps {
  message: ChatMessage;
  sessionName: string;
  onRespond: PermissionRespondFn;
  /** Sticky panel above composer — slightly tighter vertical spacing. */
  variant?: 'inline' | 'sticky';
}

export function PermissionCard({
  message,
  sessionName,
  onRespond,
  variant = 'inline',
}: PermissionCardProps) {
  const wrap = variant === 'sticky' ? '' : 'my-1.5';

  if (message.permKind === 'ask_user') {
    return (
      <div className={wrap}>
        <AskUserCard
          message={message}
          sessionName={sessionName}
          variant={variant}
          onSubmit={(sess, reqId, answers, customText) =>
            onRespond(sess, reqId, 'submit', { answers, custom_text: customText })
          }
          onSkip={(sess, reqId) => onRespond(sess, reqId, 'deny')}
        />
        <DeliveryNote state={message.permDelivery} />
      </div>
    );
  }

  if (message.permKind === 'tool_blocked') {
    const resolved = message.permResolved;
    return (
      <div className={`${wrap} rounded-md border border-warning/40 bg-warning-subtle px-3 py-2.5`}>
        <p className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold text-warning">
          <AlertCircle size={14} strokeWidth={2} />
          {message.permTitle ?? 'Tool blocked'}
        </p>
        {message.text && (
          <p className="mb-2 max-h-32 overflow-y-auto text-2xs text-fg-muted" dir="auto">
            {message.text}
          </p>
        )}
        {resolved ? (
          <p className="flex items-center gap-1 text-2xs text-success">
            <Check size={12} strokeWidth={2.5} /> Decision sent
          </p>
        ) : (
          <>
            <div className="flex flex-wrap gap-1.5">
              {(message.permOptions ?? []).map((opt) => (
                <button
                  key={opt.id}
                  type="button"
                  disabled={message.permDelivery === 'sending'}
                  onClick={() => message.actionId && onRespond(sessionName, message.actionId, opt.id)}
                  className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors duration-fast ease-tool disabled:opacity-50 ${
                    opt.id === 'allow_always'
                      ? 'bg-success text-success-contrast hover:bg-success/80'
                      : opt.id === 'allow_once'
                      ? 'bg-signal text-signal-contrast hover:bg-signal-hover'
                      : 'border border-line bg-surface text-fg-muted hover:bg-surface-overlay hover:text-fg'
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
            <DeliveryNote state={message.permDelivery} />
          </>
        )}
      </div>
    );
  }

  if (message.permKind === 'permission_denied') {
    return (
      <div className={`${wrap} flex flex-col gap-1 rounded-md border border-warning/30 bg-warning-subtle px-3 py-2 text-2xs text-warning`}>
        <div className="flex items-start gap-2">
          <AlertCircle size={13} strokeWidth={2} className="mt-0.5 flex-shrink-0" />
          <span dir="auto">{message.permTitle ?? 'Permission denied'}</span>
        </div>
        <p className="pl-5 text-fg-muted">
          Tool prompts cannot run inside DevScope headless mode. Use Act/Test mode, or switch to
          terminal Claude for interactive approvals.
        </p>
      </div>
    );
  }

  const resolved = message.permResolved;
  return (
    <div className={`${wrap} rounded-md border border-signal/40 bg-signal-subtle px-3 py-2.5`}>
      <p className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold text-signal">
        <ListChecks size={14} strokeWidth={2} />
        {message.permTitle ?? 'Plan ready — approve to proceed?'}
      </p>
      {message.text && (
        <div
          className={`mb-2 overflow-y-auto rounded-sm bg-surface/60 p-2 ${
            variant === 'sticky' ? 'max-h-40' : 'max-h-64'
          }`}
        >
          <MarkdownMessage text={message.text} />
        </div>
      )}
      {resolved ? (
        <p className="flex items-center gap-1 text-2xs text-success">
          <Check size={12} strokeWidth={2.5} /> Decision sent
        </p>
      ) : (
        <>
          <div className="flex flex-wrap gap-1.5">
            {(message.permOptions ?? []).map((opt) => (
              <button
                key={opt.id}
                type="button"
                disabled={message.permDelivery === 'sending'}
                onClick={() => message.actionId && onRespond(sessionName, message.actionId, opt.id)}
                className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors duration-fast ease-tool disabled:opacity-50 ${
                  opt.id === 'approve'
                    ? 'bg-signal text-signal-contrast hover:bg-signal-hover'
                    : 'border border-line bg-surface text-fg-muted hover:bg-surface-overlay hover:text-fg'
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
          <DeliveryNote state={message.permDelivery} />
        </>
      )}
    </div>
  );
}
