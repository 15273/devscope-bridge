/**
 * DecisionPanel — sticky panel above the composer for every pending Claude decision.
 *
 * Plan approvals, AskUserQuestion forms, and tool-blocked retries all render here
 * so the user never has to hunt in the scrollback.
 */
import type { ChatMessage } from '../store/sessionStore';
import { PermissionCard, type PermissionRespondFn } from './PermissionCard';

interface DecisionPanelProps {
  message: ChatMessage;
  sessionName: string;
  onRespond: PermissionRespondFn;
}

export function DecisionPanel({ message, sessionName, onRespond }: DecisionPanelProps) {
  if (!message.actionId || message.permResolved) return null;
  if (message.permKind === 'permission_denied') return null;

  const hasOptions = (message.permOptions?.length ?? 0) > 0;
  const hasQuestions = (message.permQuestions?.length ?? 0) > 0;
  if (!hasOptions && !hasQuestions) return null;

  return (
    <div className="relative z-20 shrink-0 max-h-[min(45vh,340px)] border-t-2 border-signal/50 bg-surface-raised px-3 py-2.5 shadow-[0_-4px_12px_rgba(0,0,0,0.06)]">
      <PermissionCard
        message={message}
        sessionName={sessionName}
        onRespond={onRespond}
        variant="sticky"
      />
    </div>
  );
}
