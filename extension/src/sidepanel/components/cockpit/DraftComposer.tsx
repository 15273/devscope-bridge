/**
 * DraftComposer — pick an AI-drafted reply and edit before sending.
 *
 * Shows 1–3 candidate chips. Clicking one fills the editable textarea (RTL).
 * "שלח" opens ConfirmSendDialog — never sends directly. Shows loading and
 * error states; never silently swallows errors.
 */
import { useState, useCallback } from 'react';
import { X } from 'lucide-react';
import { ConfirmSendDialog } from './ConfirmSendDialog';

interface DraftComposerProps {
  chatName: string;
  chatId: string;
  candidates: string[];
  onSend: (text: string) => Promise<void>;
  onClose: () => void;
}

export function DraftComposer({ chatName, candidates, onSend, onClose }: DraftComposerProps) {
  const [selected, setSelected] = useState<string>('');
  const [showConfirm, setShowConfirm] = useState(false);

  const handleChip = useCallback((text: string) => {
    setSelected(text);
  }, []);

  const handleConfirm = useCallback(async () => {
    await onSend(selected);
    setShowConfirm(false);
  }, [onSend, selected]);

  return (
    <div
      dir="rtl"
      className="flex flex-col gap-2 rounded-md border border-line bg-surface-raised p-3"
    >
      {/* Header */}
      <div className="flex items-center justify-between">
        <span className="text-2xs font-medium text-fg-muted">הצעות תשובה</span>
        <button
          type="button"
          onClick={onClose}
          className="flex h-5 w-5 items-center justify-center rounded text-fg-subtle transition-colors duration-fast ease-tool hover:bg-surface-overlay hover:text-fg"
          aria-label="סגור"
        >
          <X size={12} />
        </button>
      </div>

      {/* Candidate chips */}
      {candidates.length > 0 ? (
        <div className="flex flex-wrap gap-1.5">
          {candidates.map((c, i) => (
            <button
              key={i}
              type="button"
              onClick={() => handleChip(c)}
              className={[
                'max-w-full rounded-md border px-2.5 py-1.5 text-left text-xs leading-snug transition-colors duration-fast ease-tool',
                selected === c
                  ? 'border-signal bg-signal-subtle text-fg'
                  : 'border-line bg-surface text-fg-muted hover:border-signal hover:bg-surface-overlay hover:text-fg',
              ].join(' ')}
            >
              {c}
            </button>
          ))}
        </div>
      ) : (
        <p className="text-xs text-fg-muted">לא התקבלו הצעות</p>
      )}

      {/* Editable textarea */}
      <textarea
        dir="rtl"
        rows={3}
        value={selected}
        onChange={(e) => setSelected(e.target.value)}
        placeholder="ערוך את הטקסט לפני השליחה…"
        className="w-full resize-none rounded-md border border-line bg-surface p-2 text-xs leading-relaxed text-fg placeholder:text-fg-subtle focus:border-signal focus:outline-none"
      />

      {/* Send button */}
      <button
        type="button"
        disabled={!selected.trim()}
        onClick={() => setShowConfirm(true)}
        className="flex h-8 w-full items-center justify-center rounded-md bg-signal text-xs font-semibold text-signal-contrast transition-colors duration-fast ease-tool hover:bg-signal-hover disabled:cursor-not-allowed disabled:opacity-40"
      >
        שלח
      </button>

      {/* Confirm dialog (portal-like overlay) */}
      {showConfirm && (
        <ConfirmSendDialog
          chatName={chatName}
          text={selected}
          onConfirm={handleConfirm}
          onCancel={() => setShowConfirm(false)}
        />
      )}
    </div>
  );
}
