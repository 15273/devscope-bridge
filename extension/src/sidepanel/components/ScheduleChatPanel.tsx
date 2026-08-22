/**
 * ScheduleChatPanel — per-recurring-task chat: run digests as employee messages,
 * questions as inline-answerable cards, plus a composer that talks to the steward.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ArrowRight, ChevronDown, ChevronUp, Loader2, Pause, Play, Send, Trash2, Zap,
} from 'lucide-react';
import {
  answerTask,
  deleteSchedule,
  fetchScheduleRuns,
  parseSchedulePlaybook,
  patchSchedulePlaybook,
  runScheduleNow,
  setScheduleEnabled,
  startScheduleSteward,
  type ScheduleEntry,
  type SchedulePlaybook,
  type ScheduleRun,
} from '../bridge';
import { buildFeed, formatNextRun, formatRunTime, type FeedItem } from '../utils/scheduleFeed';

interface ScheduleChatPanelProps {
  schedule: ScheduleEntry;
  onClose: () => void;
  onRefresh: () => void;
  onOpenSession: (sessionName: string) => void;
}

export function ScheduleChatPanel({
  schedule, onClose, onRefresh, onOpenSession,
}: ScheduleChatPanelProps) {
  const [runs, setRuns] = useState<ScheduleRun[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [enabled, setEnabled] = useState(Boolean(schedule.enabled ?? true));
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [message, setMessage] = useState('');
  const [sending, setSending] = useState(false);
  const feedRef = useRef<HTMLDivElement | null>(null);

  const refreshRuns = useCallback(async () => {
    const next = await fetchScheduleRuns(schedule.id);
    setRuns(next);
    setLoaded(true);
  }, [schedule.id]);

  useEffect(() => {
    void refreshRuns();
    const timer = setInterval(() => void refreshRuns(), 5_000);
    return () => clearInterval(timer);
  }, [refreshRuns]);

  // Chat order: oldest at the top, newest at the bottom.
  const feed = buildFeed(runs).reverse();

  useEffect(() => {
    feedRef.current?.scrollTo({ top: feedRef.current.scrollHeight });
  }, [feed.length]);

  const runNow = useCallback(async () => {
    setBusyAction('run');
    await runScheduleNow(schedule.id);
    setBusyAction(null);
    onRefresh();
  }, [schedule.id, onRefresh]);

  const toggleEnabled = useCallback(async () => {
    setBusyAction('toggle');
    const next = !enabled;
    if (await setScheduleEnabled(schedule.id, next)) setEnabled(next);
    setBusyAction(null);
    onRefresh();
  }, [schedule.id, enabled, onRefresh]);

  const remove = useCallback(async () => {
    if (!confirmDelete) {
      setConfirmDelete(true);
      return;
    }
    setBusyAction('delete');
    await deleteSchedule(schedule.id);
    setBusyAction(null);
    onRefresh();
    onClose();
  }, [confirmDelete, schedule.id, onRefresh, onClose]);

  const sendToSteward = useCallback(async () => {
    const text = message.trim();
    if (!text || sending) return;
    setSending(true);
    const sessionName = await startScheduleSteward(schedule.id, text);
    setSending(false);
    if (sessionName) {
      setMessage('');
      onOpenSession(sessionName);
    }
  }, [message, sending, schedule.id, onOpenSession]);

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg border border-line bg-surface-overlay/30" dir="rtl">
      <header className="shrink-0 border-b border-line px-2.5 py-2">
        <div className="flex items-center gap-2">
          <button type="button" onClick={onClose}
            className="flex h-7 w-7 items-center justify-center rounded-md text-fg-muted hover:bg-surface-overlay">
            <ArrowRight size={16} />
          </button>
          <div className="min-w-0 flex-1">
            <h3 className="truncate text-sm font-semibold text-fg">{schedule.title}</h3>
            <p className="text-2xs text-fg-subtle">
              {enabled ? `הריצה הבאה: ${formatNextRun(schedule.next_run_at)}` : 'מושהית'}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            <HeaderBtn label="הרץ עכשיו" busy={busyAction === 'run'} onClick={() => void runNow()}>
              <Zap size={13} />
            </HeaderBtn>
            <HeaderBtn label={enabled ? 'השהה' : 'הפעל'} busy={busyAction === 'toggle'}
              onClick={() => void toggleEnabled()}>
              {enabled ? <Pause size={13} /> : <Play size={13} />}
            </HeaderBtn>
            <HeaderBtn label={confirmDelete ? 'בטוח? מחק' : 'מחק'} busy={busyAction === 'delete'}
              danger onClick={() => void remove()}>
              <Trash2 size={13} />
            </HeaderBtn>
          </div>
        </div>
      </header>

      <div ref={feedRef} className="min-h-0 flex-1 space-y-2 overflow-y-auto p-2.5">
        {!loaded ? (
          <div className="flex justify-center py-8 text-fg-muted">
            <Loader2 size={18} className="animate-spin" />
          </div>
        ) : feed.length === 0 ? (
          <p className="py-8 text-center text-xs text-fg-subtle">
            עוד לא רצתי. לחץ על ⚡ הרץ עכשיו ואחזור עם דיווח.
          </p>
        ) : (
          feed.map((item) => (
            <FeedBubble key={`${item.runId}-${item.kind}`} item={item}
              onAnswered={() => void refreshRuns()} onOpenSession={onOpenSession} />
          ))
        )}
      </div>

      <Composer value={message} onChange={setMessage} sending={sending}
        onSend={() => void sendToSteward()} />

      <AdvancedDrawer schedule={schedule} />
    </div>
  );
}

function HeaderBtn({
  label, busy, danger, onClick, children,
}: {
  label: string; busy: boolean; danger?: boolean; onClick: () => void; children: React.ReactNode;
}) {
  return (
    <button type="button" onClick={onClick} disabled={busy}
      className={`flex items-center gap-1 rounded-md border px-1.5 py-1 text-2xs disabled:opacity-50 ${
        danger
          ? 'border-danger/40 text-danger hover:bg-danger/10'
          : 'border-line text-fg-muted hover:bg-surface-overlay'
      }`}>
      {busy ? <Loader2 size={13} className="animate-spin" /> : children}
      {label}
    </button>
  );
}

function FeedBubble({
  item, onAnswered, onOpenSession,
}: {
  item: FeedItem; onAnswered: () => void; onOpenSession: (name: string) => void;
}) {
  if (item.kind === 'question') {
    return <QuestionCard item={item} onAnswered={onAnswered} />;
  }
  const tint = item.kind === 'failure'
    ? 'border-danger/30 bg-danger-subtle/40'
    : 'border-line/70 bg-surface-raised';
  return (
    <div className={`max-w-[92%] rounded-lg rounded-tr-sm border px-2.5 py-1.5 ${tint}`}>
      {item.kind === 'chief_answer' ? (
        <>
          <p className="text-2xs text-fg-subtle">שאלתי: {item.text}</p>
          <p className="mt-0.5 text-xs text-fg">
            {item.answered?.by === 'chief' ? 'המפקח ענה' : 'ענית'}: {item.answered?.text}
          </p>
        </>
      ) : (
        <p className="whitespace-pre-wrap text-xs text-fg">{item.text}</p>
      )}
      <div className="mt-1 flex flex-wrap items-center gap-1">
        {item.artifacts.map((path) => (
          <span key={path} title={path}
            className="rounded bg-surface-overlay px-1 py-0.5 font-mono text-2xs text-fg-muted">
            {path.split('/').pop()}
          </span>
        ))}
        <span className="mr-auto text-2xs text-fg-subtle">{formatRunTime(item.at)}</span>
        {item.logSession && (
          <button type="button" onClick={() => onOpenSession(item.logSession!)}
            className="text-2xs text-fg-subtle underline hover:text-fg">
            לוג
          </button>
        )}
      </div>
    </div>
  );
}

function QuestionCard({ item, onAnswered }: { item: FeedItem; onAnswered: () => void }) {
  const [answer, setAnswer] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = useCallback(async () => {
    const text = answer.trim();
    if (!text || busy) return;
    setBusy(true);
    const ok = await answerTask(item.taskId, text);
    setBusy(false);
    if (ok) onAnswered();
  }, [answer, busy, item.taskId, onAnswered]);

  return (
    <div className="max-w-[92%] rounded-lg rounded-tr-sm border border-warning/50 bg-warning-subtle/40 px-2.5 py-2">
      <p className="text-2xs font-medium text-warning">אני צריכה תשובה ממך</p>
      <p className="mt-0.5 whitespace-pre-wrap text-xs text-fg">{item.text}</p>
      <div className="mt-1.5 flex items-center gap-1.5">
        <input value={answer} onChange={(e) => setAnswer(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') void submit(); }}
          placeholder="התשובה שלך…"
          className="min-w-0 flex-1 rounded border border-line bg-surface px-2 py-1 text-xs text-fg outline-none focus:border-warning" />
        <button type="button" disabled={busy || !answer.trim()} onClick={() => void submit()}
          className="rounded-md bg-warning px-2 py-1 text-2xs font-medium text-surface disabled:opacity-50">
          {busy ? <Loader2 size={12} className="animate-spin" /> : 'ענה'}
        </button>
      </div>
    </div>
  );
}

function Composer({
  value, onChange, sending, onSend,
}: {
  value: string; onChange: (v: string) => void; sending: boolean; onSend: () => void;
}) {
  return (
    <div className="flex shrink-0 items-center gap-1.5 border-t border-line px-2.5 py-2">
      <input value={value} onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => { if (e.key === 'Enter') onSend(); }}
        placeholder="דבר עם המשימה…"
        className="min-w-0 flex-1 rounded-md border border-line bg-surface px-2.5 py-1.5 text-xs text-fg outline-none focus:border-signal" />
      <button type="button" disabled={sending || !value.trim()} onClick={onSend}
        className="flex h-7 w-7 items-center justify-center rounded-md bg-signal text-signal-contrast disabled:opacity-50">
        {sending ? <Loader2 size={13} className="animate-spin" /> : <Send size={13} />}
      </button>
    </div>
  );
}

function AdvancedDrawer({ schedule }: { schedule: ScheduleEntry }) {
  const [open, setOpen] = useState(false);
  const [json, setJson] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setJson(JSON.stringify(parseSchedulePlaybook(schedule.playbook), null, 2));
  }, [schedule]);

  const save = useCallback(async () => {
    let patch: Partial<SchedulePlaybook>;
    try {
      patch = JSON.parse(json) as Partial<SchedulePlaybook>;
    } catch {
      setError('JSON לא תקין');
      return;
    }
    setBusy(true);
    setError(null);
    const ok = await patchSchedulePlaybook(schedule.id, patch);
    setBusy(false);
    if (!ok) setError('שמירה נכשלה');
  }, [json, schedule.id]);

  return (
    <div className="shrink-0 border-t border-line">
      <button type="button" onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-1 px-2.5 py-1.5 text-2xs text-fg-subtle hover:text-fg">
        {open ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
        מתקדם — Playbook
      </button>
      {open && (
        <div className="space-y-1.5 px-2.5 pb-2">
          <textarea value={json} onChange={(e) => setJson(e.target.value)} rows={8} dir="ltr"
            className="w-full resize-none rounded border border-line bg-surface px-2 py-1.5 font-mono text-2xs text-fg outline-none focus:border-signal" />
          {error && <p className="text-2xs text-danger">{error}</p>}
          <button type="button" disabled={busy} onClick={() => void save()}
            className="rounded-md bg-signal px-2 py-1 text-2xs text-signal-contrast disabled:opacity-50">
            {busy ? 'שומר…' : 'שמור playbook'}
          </button>
        </div>
      )}
    </div>
  );
}
