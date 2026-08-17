/**
 * ConfirmMetaActionDialog — gate for pause/budget changes on Meta campaigns.
 */
import type { MetaActionPreview } from './useMetaAds';

interface ConfirmMetaActionDialogProps {
  preview: MetaActionPreview;
  actionLabel: string;
  onConfirm: () => void | Promise<void>;
  onCancel: () => void;
}

export function ConfirmMetaActionDialog({
  preview,
  actionLabel,
  onConfirm,
  onCancel,
}: ConfirmMetaActionDialogProps) {
  const before = preview.before;
  const after = preview.after;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      dir="rtl"
      role="dialog"
      aria-modal="true"
    >
      <div className="w-full max-w-sm rounded-lg border border-line bg-surface-raised p-4 shadow-lg">
        <h3 className="text-sm font-semibold text-fg">אישור שינוי — {actionLabel}</h3>
        <p className="mt-1 text-2xs text-fg-muted">{before.name}</p>
        <div className="mt-3 space-y-2 rounded-md border border-line bg-surface p-2 text-2xs">
          <div>
            <span className="text-fg-subtle">לפני: </span>
            <span className="text-fg">
              {before.status}
              {before.daily_budget != null ? ` · תקציב ${before.daily_budget}` : ''}
            </span>
          </div>
          <div>
            <span className="text-fg-subtle">אחרי: </span>
            <span className="font-medium text-signal">
              {after.status}
              {after.daily_budget != null ? ` · תקציב ${after.daily_budget}` : ''}
            </span>
          </div>
        </div>
        <div className="mt-4 flex gap-2">
          <button
            type="button"
            onClick={() => void onConfirm()}
            className="flex-1 rounded-md bg-signal py-2 text-xs font-medium text-signal-contrast"
          >
            אשר
          </button>
          <button
            type="button"
            onClick={onCancel}
            className="flex-1 rounded-md border border-line py-2 text-xs text-fg-muted"
          >
            ביטול
          </button>
        </div>
      </div>
    </div>
  );
}
