/**
 * TaskApprovalPanel — pending sensitive-action approvals from orchestrator workers.
 * action='question' entries render as an answerable question instead of approve/reject.
 */
import { useState } from 'react';
import { AlertTriangle, HelpCircle, Loader2 } from 'lucide-react';
import type { PendingApproval } from '../bridge';
import { answerTask, approveTask, rejectTask } from '../bridge';

const ACTION_LABEL: Record<string, string> = {
  send: 'שליחה / submit',
  send_email: 'שליחת מייל',
  delete: 'מחיקה',
  purchase: 'רכישה',
  money: 'תשלום / כסף',
};

interface TaskApprovalPanelProps {
  approvals: PendingApproval[];
  onResolved: () => void;
}

function payloadPreview(payload: Record<string, unknown>): string {
  const keys = Object.keys(payload);
  if (keys.length === 0) return '';
  try {
    const text = JSON.stringify(payload, null, 0);
    return text.length > 180 ? `${text.slice(0, 180)}…` : text;
  } catch {
    return '';
  }
}

function ApprovalCard({
  item,
  onResolved,
}: {
  item: PendingApproval;
  onResolved: () => void;
}) {
  const [busy, setBusy] = useState<'approve' | 'reject' | null>(null);
  const [err, setErr] = useState('');

  const actionLabel = ACTION_LABEL[item.action] ?? item.action;
  const preview = payloadPreview(item.payload ?? {});

  const decide = async (approved: boolean) => {
    setBusy(approved ? 'approve' : 'reject');
    setErr('');
    const ok = approved ? await approveTask(item.task_id) : await rejectTask(item.task_id);
    setBusy(null);
    if (!ok) {
      setErr('הפעולה נכשלה — נסה שוב');
      return;
    }
    onResolved();
  };

  return (
    <li className="rounded-md border border-warning/40 bg-warning-subtle/30 px-2.5 py-2">
      <div className="flex items-start gap-2">
        <AlertTriangle size={14} className="mt-0.5 shrink-0 text-warning" aria-hidden />
        <div className="min-w-0 flex-1">
          <p className="truncate text-xs font-semibold text-fg" title={item.title}>
            {item.title}
          </p>
          <p className="mt-0.5 text-2xs text-fg-muted">
            פעולה: <span className="font-medium text-fg">{actionLabel}</span>
          </p>
          {preview && (
            <pre className="mt-1 max-h-16 overflow-auto rounded bg-surface-overlay/80 p-1.5 font-mono text-2xs text-fg-subtle">
              {preview}
            </pre>
          )}
          {err && <p className="mt-1 text-2xs text-danger">{err}</p>}
        </div>
      </div>
      <div className="mt-2 flex justify-end gap-1.5">
        <button
          type="button"
          disabled={busy !== null}
          onClick={() => void decide(false)}
          className="rounded-md border border-line px-2.5 py-1 text-2xs font-medium text-fg-muted hover:bg-surface-overlay disabled:opacity-50"
        >
          {busy === 'reject' ? <Loader2 size={12} className="animate-spin" /> : 'דחה'}
        </button>
        <button
          type="button"
          disabled={busy !== null}
          onClick={() => void decide(true)}
          className="rounded-md bg-signal px-2.5 py-1 text-2xs font-medium text-signal-contrast hover:opacity-90 disabled:opacity-50"
        >
          {busy === 'approve' ? <Loader2 size={12} className="animate-spin" /> : 'אשר'}
        </button>
      </div>
    </li>
  );
}

function QuestionCard({
  item,
  onResolved,
}: {
  item: PendingApproval;
  onResolved: () => void;
}) {
  const [answer, setAnswer] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  const payload = (item.payload ?? {}) as { question?: string; options?: string[] };
  const options = Array.isArray(payload.options) ? payload.options.slice(0, 4) : [];

  const submit = async (text: string) => {
    if (!text.trim()) return;
    setBusy(true);
    setErr('');
    const ok = await answerTask(item.task_id, text.trim());
    setBusy(false);
    if (!ok) {
      setErr('שליחת התשובה נכשלה — נסה שוב');
      return;
    }
    onResolved();
  };

  return (
    <li className="rounded-md border border-signal/40 bg-signal-subtle/20 px-2.5 py-2">
      <div className="flex items-start gap-2">
        <HelpCircle size={14} className="mt-0.5 shrink-0 text-signal" aria-hidden />
        <div className="min-w-0 flex-1">
          <p className="truncate text-xs font-semibold text-fg" title={item.title}>
            {item.title}
          </p>
          <p className="mt-0.5 whitespace-pre-wrap text-2xs text-fg">
            {payload.question || 'הסוכן ממתין לתשובה'}
          </p>
          {options.length > 0 && (
            <div className="mt-1.5 flex flex-wrap gap-1">
              {options.map((opt) => (
                <button
                  key={opt}
                  type="button"
                  disabled={busy}
                  onClick={() => void submit(opt)}
                  className="rounded-full border border-line px-2 py-0.5 text-2xs text-fg-muted hover:bg-surface-overlay disabled:opacity-50"
                >
                  {opt}
                </button>
              ))}
            </div>
          )}
          {err && <p className="mt-1 text-2xs text-danger">{err}</p>}
        </div>
      </div>
      <form
        className="mt-2 flex gap-1.5"
        onSubmit={(e) => {
          e.preventDefault();
          void submit(answer);
        }}
      >
        <input
          value={answer}
          onChange={(e) => setAnswer(e.target.value)}
          placeholder="ענה כאן…"
          className="min-w-0 flex-1 rounded-md border border-line bg-surface px-2 py-1 text-2xs text-fg placeholder:text-fg-subtle"
        />
        <button
          type="submit"
          disabled={busy || !answer.trim()}
          className="rounded-md bg-signal px-2.5 py-1 text-2xs font-medium text-signal-contrast hover:opacity-90 disabled:opacity-50"
        >
          {busy ? <Loader2 size={12} className="animate-spin" /> : 'שלח'}
        </button>
      </form>
    </li>
  );
}

export function TaskApprovalPanel({ approvals, onResolved }: TaskApprovalPanelProps) {
  if (approvals.length === 0) return null;

  return (
    <section
      className="shrink-0 rounded-lg border border-warning/50 bg-warning-subtle/20 p-2"
      aria-label="ממתין לאישור"
    >
      <header className="mb-1.5 flex items-center justify-between px-0.5">
        <h3 className="text-xs font-semibold text-warning">
          ממתין לאישור ({approvals.length})
        </h3>
      </header>
      <ul className="max-h-48 space-y-1.5 overflow-y-auto">
        {approvals.map((item) =>
          item.action === 'question' ? (
            <QuestionCard key={item.id} item={item} onResolved={onResolved} />
          ) : (
            <ApprovalCard key={item.id} item={item} onResolved={onResolved} />
          ),
        )}
      </ul>
    </section>
  );
}
