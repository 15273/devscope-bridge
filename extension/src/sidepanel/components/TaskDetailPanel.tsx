/**
 * TaskDetailPanel — task metadata, log timeline, open worker session, cancel.
 */
import { useCallback, useEffect, useState } from 'react';
import { ArrowRight, ExternalLink, Loader2, Trash2 } from 'lucide-react';
import {
  cancelTask,
  fetchTaskDetail,
  workerSessionForTask,
  type AgentTask,
  type TaskDetail,
} from '../bridge';
import { formatTaskUsageChip, formatUsageTokens, taskUsageTokens } from '../utils/taskUsageFormat';

const STATUS_LABEL: Record<string, string> = {
  new: 'חדש',
  assigned: 'מוקצה',
  ready: 'מוכן',
  in_progress: 'רץ',
  awaiting_approval: 'ממתין לאישור',
  approved: 'אושר',
  done: 'הושלם',
  failed: 'נכשל',
  cancelled: 'בוטל',
};

const TERMINAL = new Set(['done', 'failed', 'cancelled']);

interface TaskDetailPanelProps {
  taskId: string;
  childTasks: AgentTask[];
  knownSessions: Set<string>;
  onClose: () => void;
  onRefreshBoard: () => void;
  onOpenWorkerSession: (sessionName: string) => void;
}

export function TaskDetailPanel({
  taskId,
  childTasks,
  knownSessions,
  onClose,
  onRefreshBoard,
  onOpenWorkerSession,
}: TaskDetailPanelProps) {
  const [detail, setDetail] = useState<TaskDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    const data = await fetchTaskDetail(taskId);
    if (!data) {
      setError('לא ניתן לטעון את המשימה');
      setDetail(null);
    } else {
      setDetail(data);
    }
    setLoading(false);
  }, [taskId]);

  useEffect(() => {
    void load();
  }, [load]);

  const task = detail?.task;
  const workerName = task ? workerSessionForTask(task) : null;
  const canOpenWorker =
    Boolean(workerName) &&
    (knownSessions.has(workerName!) ||
      task?.status === 'in_progress' ||
      task?.status === 'approved' ||
      Boolean(task?.assignee_session));

  const handleCancel = async () => {
    if (!task || TERMINAL.has(task.status)) return;
    setCancelling(true);
    const ok = await cancelTask(task.id);
    setCancelling(false);
    if (!ok) {
      setError('ביטול המשימה נכשל');
      return;
    }
    onRefreshBoard();
    await load();
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg border border-line bg-surface-overlay/30">
      <header className="flex shrink-0 items-center gap-2 border-b border-line px-2.5 py-2">
        <button
          type="button"
          onClick={onClose}
          className="flex h-7 w-7 items-center justify-center rounded-md text-fg-muted hover:bg-surface-overlay"
          aria-label="חזרה ללוח"
        >
          <ArrowRight size={16} />
        </button>
        <h3 className="min-w-0 flex-1 truncate text-sm font-semibold text-fg">
          {task?.title ?? 'פרטי משימה'}
        </h3>
        {task && !TERMINAL.has(task.status) && (
          <button
            type="button"
            disabled={cancelling}
            onClick={() => void handleCancel()}
            className="flex items-center gap-1 rounded-md border border-line px-2 py-1 text-2xs text-danger hover:bg-danger-subtle disabled:opacity-50"
          >
            {cancelling ? <Loader2 size={12} className="animate-spin" /> : <Trash2 size={12} />}
            בטל
          </button>
        )}
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto p-2.5">
        {loading && (
          <div className="flex justify-center py-8 text-fg-muted">
            <Loader2 size={20} className="animate-spin" />
          </div>
        )}
        {error && !loading && <p className="text-xs text-danger">{error}</p>}

        {task && !loading && (
          <div className="space-y-3">
            <MetaRow label="סטטוס" value={STATUS_LABEL[task.status] ?? task.status} />
            <MetaRow label="סוג" value={task.kind} />
            {task.domain && <MetaRow label="domain" value={task.domain} />}
            {task.autonomy && <MetaRow label="autonomy" value={task.autonomy} />}
            {task.instruction && (
              <div>
                <p className="mb-0.5 text-2xs text-fg-subtle">הוראות</p>
                <p className="whitespace-pre-wrap text-xs text-fg">{task.instruction}</p>
              </div>
            )}
            {task.result_summary && (
              <div>
                <p className="mb-0.5 text-2xs text-fg-subtle">תוצאה</p>
                <p className="whitespace-pre-wrap text-xs text-fg-muted">{task.result_summary}</p>
              </div>
            )}

            {taskUsageTokens(task) > 0 && (
              <div className="rounded-md border border-line/60 bg-surface-raised px-2.5 py-2">
                <p className="mb-1.5 text-2xs font-medium text-fg-subtle">שימוש בטוקנים</p>
                <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
                  <UsageRow label="סה״כ" value={formatTaskUsageChip(task) ?? '—'} />
                  {(task.usage_turn_count ?? 0) > 0 && (
                    <UsageRow label="turns" value={String(task.usage_turn_count)} />
                  )}
                  {(task.usage_input_tokens ?? 0) > 0 && (
                    <UsageRow label="input" value={formatUsageTokens(task.usage_input_tokens!)} />
                  )}
                  {(task.usage_output_tokens ?? 0) > 0 && (
                    <UsageRow label="output" value={formatUsageTokens(task.usage_output_tokens!)} />
                  )}
                  {(task.usage_cache_read_tokens ?? 0) > 0 && (
                    <UsageRow label="cache read" value={formatUsageTokens(task.usage_cache_read_tokens!)} />
                  )}
                </div>
              </div>
            )}

            {canOpenWorker && workerName && (
              <button
                type="button"
                onClick={() => onOpenWorkerSession(workerName)}
                className="flex w-full items-center justify-center gap-1.5 rounded-md bg-signal px-3 py-2 text-xs font-medium text-signal-contrast hover:opacity-90"
              >
                <ExternalLink size={14} />
                פתח סשן {workerName}
              </button>
            )}

            {childTasks.length > 0 && (
              <div>
                <p className="mb-1 text-2xs font-medium text-fg-subtle">יחידות worker</p>
                <ul className="space-y-1">
                  {childTasks.map((c) => {
                    const chip = formatTaskUsageChip(c);
                    return (
                    <li
                      key={c.id}
                      className="rounded border border-line/60 bg-surface-raised px-2 py-1 text-2xs text-fg-muted"
                    >
                      {c.title} · {STATUS_LABEL[c.status] ?? c.status}
                      {chip && <span className="mr-1 font-mono tabular-nums text-fg-subtle"> · {chip}</span>}
                    </li>
                    );
                  })}
                </ul>
              </div>
            )}

            <div>
              <p className="mb-1 text-2xs font-medium text-fg-subtle">לוג ({detail?.logs.length ?? 0})</p>
              {detail?.logs.length === 0 ? (
                <p className="text-2xs text-fg-subtle">אין רשומות עדיין</p>
              ) : (
                <ol className="space-y-1.5">
                  {[...(detail?.logs ?? [])].reverse().map((log) => (
                    <li
                      key={log.id}
                      className="rounded-md border border-line/50 bg-surface-raised px-2 py-1.5"
                    >
                      <div className="flex flex-wrap items-center gap-1.5 text-2xs text-fg-subtle">
                        <span className="font-mono tabular-nums">{log.ts}</span>
                        {log.actor && <span>{log.actor}</span>}
                      </div>
                      <p className="mt-0.5 whitespace-pre-wrap text-xs text-fg">{log.message}</p>
                    </li>
                  ))}
                </ol>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function MetaRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-2 text-xs">
      <span className="shrink-0 text-fg-subtle">{label}</span>
      <span className="text-fg">{value}</span>
    </div>
  );
}

function UsageRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-2">
      <span className="text-fg-subtle">{label}</span>
      <span className="font-mono tabular-nums text-fg">{value}</span>
    </div>
  );
}
