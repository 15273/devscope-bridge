/**
 * TaskBoard — orchestrator queue with detail drill-down and worker session link.
 */
import { useMemo, useState, useEffect, type ReactNode } from 'react';
import type { Agent } from '@/shared/frames';
import { Loader2, RefreshCw } from 'lucide-react';
import type { AgentTask, TaskBoardSnapshot } from '../bridge';
import { formatTaskUsageChip } from '../utils/taskUsageFormat';
import { TaskApprovalPanel } from './TaskApprovalPanel';
import { TaskDetailPanel } from './TaskDetailPanel';
import { SchedulePanel } from './SchedulePanel';
import { NewScheduleModal } from './NewScheduleModal';

interface TaskBoardProps {
  board: TaskBoardSnapshot | null;
  loading: boolean;
  error: string | null;
  sessionNames: string[];
  activeSession: string | null;
  onOpenSetupChat: (setupSessionName: string, agent: Agent) => void;
  domainFilter: string | null;
  onDomainFilterChange: (domain: string | null) => void;
  onRefresh: () => void;
  onNewTask: () => void;
  onOpenWorkerSession: (sessionName: string) => void;
}

const DOMAIN_OPTIONS = ['', 'browser', 'research', 'dev'] as const;

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

const THROTTLE_LABEL: Record<string, string> = {
  full_speed: 'מהירות מלאה',
  mid_utilization: 'האטה בינונית (quota)',
  high_utilization: 'האטה חזקה (quota)',
  throttle_disabled: 'throttle כבוי',
  quota_unavailable: 'quota לא זמין',
  no_five_hour_bucket: 'אין נתוני 5h',
};

function groupTasks(tasks: AgentTask[]) {
  const queue: AgentTask[] = [];
  const running: AgentTask[] = [];
  const done: AgentTask[] = [];
  for (const t of tasks) {
    if (['new', 'assigned', 'ready'].includes(t.status)) queue.push(t);
    else if (['in_progress', 'awaiting_approval', 'approved'].includes(t.status)) running.push(t);
    else if (['done', 'failed', 'cancelled'].includes(t.status)) done.push(t);
  }
  return { queue, running, done };
}

function TaskColumn({
  title,
  tasks,
  accent,
  onSelect,
}: {
  title: string;
  tasks: AgentTask[];
  accent: string;
  onSelect: (id: string) => void;
}) {
  return (
    <section className="flex min-h-0 flex-1 flex-col rounded-lg border border-line bg-surface-overlay/40">
      <header
        className={`flex items-center justify-between border-b border-line px-2.5 py-1.5 text-xs font-medium ${accent}`}
      >
        <span>{title}</span>
        <span className="tabular-nums text-fg-subtle">{tasks.length}</span>
      </header>
      <ul className="flex-1 space-y-1 overflow-y-auto p-1.5">
        {tasks.length === 0 ? (
          <li className="px-1 py-3 text-center text-2xs text-fg-subtle">—</li>
        ) : (
          tasks.map((t) => <TaskCard key={t.id} task={t} onSelect={onSelect} />)
        )}
      </ul>
    </section>
  );
}

function TaskCard({ task, onSelect }: { task: AgentTask; onSelect: (id: string) => void }) {
  const status = STATUS_LABEL[task.status] ?? task.status;
  const usageChip = formatTaskUsageChip(task);
  return (
    <li>
      <button
        type="button"
        onClick={() => onSelect(task.id)}
        className="w-full rounded-md border border-line/70 bg-surface-raised px-2 py-1.5 text-right transition-colors hover:border-signal/40 hover:bg-surface-overlay"
      >
        <p className="truncate text-xs font-medium text-fg" title={task.title}>
          {task.title}
        </p>
        <div className="mt-0.5 flex flex-wrap items-center gap-1 text-2xs text-fg-subtle">
          <span className="rounded bg-surface-overlay px-1 py-0.5">{status}</span>
          {task.domain && <span>{task.domain}</span>}
          {task.source === 'notion' && (
            <span className="rounded bg-signal-subtle px-1 py-0.5 text-signal">Notion</span>
          )}
          {task.autonomy === 'e2e' && <span className="text-warning">E2E</span>}
          {usageChip && (
            <span
              className="rounded bg-surface-overlay px-1 py-0.5 font-mono tabular-nums text-fg-muted"
              title="טוקנים · עלות משוערת (כולל worker units)"
            >
              {usageChip}
            </span>
          )}
        </div>
        {task.progress && task.progress.total > 0 && (
          <div
            className="mt-1.5 flex items-center gap-1.5"
            title={`${task.progress.done}/${task.progress.total} steps done`}
          >
            <div className="h-1 flex-1 overflow-hidden rounded-full bg-surface-overlay">
              <div
                className="h-full rounded-full bg-signal transition-all"
                style={{ width: `${task.progress.pct}%` }}
              />
            </div>
            <span className="font-mono text-2xs tabular-nums text-fg-subtle">
              {task.progress.pct}%
            </span>
          </div>
        )}
        {task.result_summary && (
          <p className="mt-1 line-clamp-2 text-2xs text-fg-muted">{task.result_summary}</p>
        )}
      </button>
    </li>
  );
}

function formatUsageStat(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1000) return `${(n / 1000).toFixed(0)}k`;
  return String(n);
}

function tickCountdown(nextTickAt: string | null | undefined): string {
  if (!nextTickAt) return '—';
  const target = new Date(nextTickAt.replace(' ', 'T')).getTime();
  const diff = target - Date.now();
  if (diff <= 0) return 'קרוב';
  const mins = Math.floor(diff / 60_000);
  if (mins >= 60) {
    const h = Math.floor(mins / 60);
    const m = mins % 60;
    return `${h}:${String(m).padStart(2, '0')} ש`;
  }
  return `${mins} דק׳`;
}

function RuntimeBar({ board }: { board: TaskBoardSnapshot }) {
  const { runtime, config, mom } = board;
  const throttle = runtime.throttle;
  const util = throttle.utilization;
  const [countdown, setCountdown] = useState(() => tickCountdown(runtime.next_tick_at));

  useEffect(() => {
    setCountdown(tickCountdown(runtime.next_tick_at));
    const id = setInterval(() => setCountdown(tickCountdown(runtime.next_tick_at)), 30_000);
    return () => clearInterval(id);
  }, [runtime.next_tick_at]);

  return (
    <div className="space-y-2">
      {config.paused && (
        <p className="rounded-md border border-amber-500/40 bg-amber-500/10 px-2.5 py-1.5 text-xs text-amber-200" dir="rtl">
          התור מושהה — workers קיימים ימשיכו, dispatch חדש לא יצא עד שתבטל pause.
        </p>
      )}
      <div
        className="grid grid-cols-2 gap-2 rounded-lg border border-line bg-surface-overlay/30 p-2.5 text-xs sm:grid-cols-3 lg:grid-cols-6"
        dir="rtl"
      >
        <Stat label="בתור" value={String(runtime.queued_ready)} />
        <Stat label="רץ עכשיו" value={`${runtime.running_workers} / ${runtime.effective_max_workers}`} />
        <Stat label="tick הבא" value={countdown} hint={runtime.next_tick_at ?? undefined} />
        <Stat label="24ש הושלמו" value={String(runtime.completed_24h ?? 0)} />
        {runtime.usage_24h && runtime.usage_24h.total_tokens > 0 && (
          <Stat
            label={`טוקנים (${runtime.usage_24h.hours}ש)`}
            value={formatUsageStat(runtime.usage_24h.total_tokens)}
            hint={
              runtime.usage_24h.total_cost_usd > 0
                ? `$${runtime.usage_24h.total_cost_usd.toFixed(2)} · ${runtime.usage_24h.tasks_with_usage} משימות`
                : `${runtime.usage_24h.tasks_with_usage} משימות`
            }
          />
        )}
        <Stat
          label="קצב"
          value={THROTTLE_LABEL[throttle.reason] ?? throttle.reason}
          hint={util != null ? `${Math.round(util)}% quota` : undefined}
        />
      </div>
      {mom?.report && (
        <details className="rounded-lg border border-line bg-surface-overlay/20 px-2.5 py-2 text-xs" dir="rtl">
          <summary className="cursor-pointer font-medium text-fg-subtle">
            דוח MoM {mom.report_at ? `· ${mom.report_at}` : ''}
          </summary>
          <p className="mt-2 whitespace-pre-wrap text-fg-muted">{mom.report}</p>
        </details>
      )}
    </div>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div>
      <p className="text-2xs text-fg-subtle">{label}</p>
      <p className="font-medium tabular-nums text-fg">{value}</p>
      {hint && <p className="text-2xs text-fg-subtle">{hint}</p>}
    </div>
  );
}

export function TaskBoard({
  board,
  loading,
  error,
  sessionNames,
  activeSession,
  onOpenSetupChat,
  domainFilter,
  onDomainFilterChange,
  onRefresh,
  onNewTask,
  onOpenWorkerSession,
}: TaskBoardProps) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [tab, setTab] = useState<'board' | 'schedules'>('board');
  const [showNewSchedule, setShowNewSchedule] = useState(false);
  const groups = useMemo(() => groupTasks(board?.tasks ?? []), [board?.tasks]);
  const knownSessions = useMemo(() => new Set(sessionNames), [sessionNames]);
  const childTasks = useMemo(
    () => (selectedId ? (board?.tasks ?? []).filter((t) => t.parent_id === selectedId) : []),
    [board?.tasks, selectedId],
  );

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-hidden p-3" dir="rtl">
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-1">
          <h2 className="text-sm font-semibold text-fg">משימות</h2>
          <div className="mr-2 flex rounded-md border border-line p-0.5 text-2xs">
            <TabBtn active={tab === 'board'} onClick={() => { setTab('board'); setSelectedId(null); }}>
              לוח
            </TabBtn>
            <TabBtn active={tab === 'schedules'} onClick={() => { setTab('schedules'); setSelectedId(null); }}>
              מתוזמנות
            </TabBtn>
          </div>
        </div>
        <div className="flex items-center gap-1">
          {tab === 'board' && (
            <select
              value={domainFilter ?? ''}
              onChange={(e) => onDomainFilterChange(e.target.value || null)}
              className="rounded-md border border-line bg-surface px-2 py-1 text-2xs text-fg"
            >
              {DOMAIN_OPTIONS.map((d) => (
                <option key={d || 'all'} value={d}>{d || 'כל ה-domains'}</option>
              ))}
            </select>
          )}
          <button
            type="button"
            onClick={onRefresh}
            className="flex h-7 w-7 items-center justify-center rounded-md text-fg-muted hover:bg-surface-overlay"
            aria-label="רענון"
          >
            <RefreshCw size={14} />
          </button>
          {tab === 'board' ? (
            <button
              type="button"
              onClick={onNewTask}
              className="rounded-md bg-signal px-2.5 py-1 text-xs font-medium text-signal-contrast hover:opacity-90"
            >
              משימה חדשה
            </button>
          ) : (
            <button
              type="button"
              onClick={() => setShowNewSchedule(true)}
              className="rounded-md bg-signal px-2.5 py-1 text-xs font-medium text-signal-contrast hover:opacity-90"
            >
              תזמון חדש
            </button>
          )}
        </div>
      </div>

      {loading && !board && (
        <div className="flex flex-1 items-center justify-center text-fg-muted">
          <Loader2 size={20} className="animate-spin" />
        </div>
      )}
      {error && <p className="text-xs text-danger">{error}</p>}
      {board && tab === 'schedules' && (
        <SchedulePanel
          schedules={board.schedules ?? []}
          onRefresh={onRefresh}
          onNewSchedule={() => setShowNewSchedule(true)}
        />
      )}
      {board && tab === 'board' && (
        <>
          {!selectedId && <RuntimeBar board={board} />}
          {!selectedId && (
            <TaskApprovalPanel approvals={board.pending_approvals} onResolved={onRefresh} />
          )}
          {selectedId ? (
            <TaskDetailPanel
              taskId={selectedId}
              childTasks={childTasks}
              knownSessions={knownSessions}
              onClose={() => setSelectedId(null)}
              onRefreshBoard={onRefresh}
              onOpenWorkerSession={onOpenWorkerSession}
            />
          ) : (
            <div className="flex min-h-0 flex-1 gap-2">
              <TaskColumn title="תור" tasks={groups.queue} accent="text-fg-muted" onSelect={setSelectedId} />
              <TaskColumn title="רץ" tasks={groups.running} accent="text-signal" onSelect={setSelectedId} />
              <TaskColumn
                title="הושלם / נכשל"
                tasks={groups.done.slice(0, 40)}
                accent="text-fg-subtle"
                onSelect={setSelectedId}
              />
            </div>
          )}
        </>
      )}
      {showNewSchedule && (
        <NewScheduleModal
          sessionName={activeSession}
          onOpenSetupChat={onOpenSetupChat}
          onClose={() => setShowNewSchedule(false)}
          onCreated={onRefresh}
        />
      )}
    </div>
  );
}

function TabBtn({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded px-2 py-0.5 ${active ? 'bg-surface-raised font-medium text-fg' : 'text-fg-subtle'}`}
    >
      {children}
    </button>
  );
}
