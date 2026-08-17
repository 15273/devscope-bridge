/**
 * ConfirmSendDialog — mandatory send gate before dispatching to WhatsApp.
 *
 * Shows the target chat name + the exact text in a quoted block.
 * Only on "אישור ושליחה" does it call `onConfirm`.
 * On error the dialog stays open and surfaces the message.
 * This is a real send — the visual treatment makes that unmistakably clear.
 */
import { useState, useCallback } from 'react';
import { MessageCircle } from 'lucide-react';

interface ConfirmSendDialogProps {
  chatName: string;
  text: string;
  onConfirm: () => Promise<void>;
  onCancel: () => void;
}

export function ConfirmSendDialog({ chatName, text, onConfirm, onCancel }: ConfirmSendDialogProps) {
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);

  const handleConfirm = useCallback(async () => {
    setSending(true);
    setSendError(null);
    try {
      await onConfirm();
      // success: parent closes the dialog by unmounting us
    } catch (e) {
      setSendError(e instanceof Error ? e.message : String(e));
      setSending(false);
    }
  }, [onConfirm]);

  return (
    /* Backdrop */
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      dir="rtl"
    >
      {/* Card */}
      <div className="flex w-[320px] max-w-[calc(100vw-32px)] flex-col gap-4 rounded-xl border border-line bg-surface p-5 shadow-modal">
        {/* Header */}
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-signal-subtle">
            <MessageCircle size={16} className="text-signal" />
          </div>
          <div>
            <p className="text-xs font-semibold text-fg">שליחת הודעה ב-WhatsApp</p>
            <p className="text-2xs text-fg-muted">לשיחה עם {chatName}</p>
          </div>
        </div>

        {/* Quoted text block */}
        <div className="rounded-md border border-line bg-surface-overlay p-3">
          <p className="whitespace-pre-wrap break-words text-xs leading-relaxed text-fg">
            {text}
          </p>
        </div>

        {/* Warning */}
        <p className="text-2xs text-fg-muted">
          ההודעה תישלח מיד לשיחת WhatsApp. לא ניתן לבטל לאחר השליחה.
        </p>

        {/* Send error */}
        {sendError && (
          <p className="rounded-sm bg-danger-subtle px-2 py-1.5 text-2xs text-danger">
            שגיאה: {sendError}
          </p>
        )}

        {/* Buttons */}
        <div className="flex gap-2">
          <button
            type="button"
            disabled={sending}
            onClick={handleConfirm}
            className="flex h-9 flex-1 items-center justify-center rounded-md bg-signal text-xs font-semibold text-signal-contrast transition-colors duration-fast ease-tool hover:bg-signal-hover disabled:cursor-wait disabled:opacity-60"
          >
            {sending ? 'שולח…' : 'אישור ושליחה'}
          </button>
          <button
            type="button"
            disabled={sending}
            onClick={onCancel}
            className="flex h-9 flex-1 items-center justify-center rounded-md border border-line bg-surface text-xs font-medium text-fg transition-colors duration-fast ease-tool hover:bg-surface-overlay disabled:opacity-40"
          >
            ביטול
          </button>
        </div>
      </div>
    </div>
  );
}
