/**
 * NewScheduleModal — wizard with Claude/Cursor engine + dedicated setup chat.
 */
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { ChevronLeft, ChevronRight, Eye, Loader2, Map, MessageSquare, RefreshCw, X } from 'lucide-react';
import type { Agent, AgentMode } from '@/shared/frames';
import { AGENTS, AGENT_LABELS } from '@/shared/agents';
import { createSchedule, type SchedulePlaybook } from '../bridge';
import {
  LINKEDIN_WATCH_INSTRUCTION,
  LINKEDIN_WATCH_TITLE,
  linkedinWatchPlaybook,
} from '../linkedinWatchPreset';
import { discoverSchedulePlaybook } from '../integrations/scheduleDiscover';
import {
  bootstrapScheduleSetup,
  completeScheduleSetup,
  fetchActiveSetupDraft,
  fetchSetupDraft,
  startScheduleSetup,
  type ScheduleSetupDraft,
} from '../integrations/scheduleSetup';

const DOMAINS = ['browser', 'research', 'dev'] as const;
const STEPS = ['מטרה', 'מיפוי', 'סיום'] as const;
type Step = (typeof STEPS)[number];
type Recurrence = 'daily' | 'hourly' | 'every_30';
const FEED_URL = 'https://www.linkedin.com/feed/';

function parseKeywords(raw: string): string[] {
  return raw.split(/[,|\n]/).map((s) => s.trim()).filter(Boolean);
}

interface NewScheduleModalProps {
  sessionName: string | null;
  onOpenSetupChat: (setupSessionName: string, agent: Agent) => void;
  onClose: () => void;
  onCreated: () => void;
}

function computeNextRun(recurrence: Recurrence, dailyAt: string): string {
  const now = new Date();
  if (recurrence === 'hourly') {
    now.setHours(now.getHours() + 1, 0, 0, 0);
    return formatTs(now);
  }
  if (recurrence === 'every_30') {
    now.setMinutes(now.getMinutes() + 30);
    return formatTs(now);
  }
  const [hh, mm] = dailyAt.split(':').map(Number);
  const target = new Date(now);
  target.setHours(hh, mm, 0, 0);
  if (target <= now) target.setDate(target.getDate() + 1);
  return formatTs(target);
}

function formatTs(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:00`;
}

function emptyPlaybook(): SchedulePlaybook {
  return { version: 1, entry_urls: [], workflow: [], selectors: {}, checklist: [], notes: '' };
}

function applyDraft(draft: ScheduleSetupDraft) {
  return {
    title: draft.title,
    instruction: draft.instruction ?? '',
    domain: draft.domain,
    entryUrl: draft.entry_url,
    agent: draft.agent,
    runtimeMode: (draft.runtime_mode ?? 'act') as AgentMode,
    playbook: draft.playbook,
  };
}

export function NewScheduleModal({
  sessionName,
  onOpenSetupChat,
  onClose,
  onCreated,
}: NewScheduleModalProps) {
  const [step, setStep] = useState<Step>('מטרה');
  const [title, setTitle] = useState('');
  const [instruction, setInstruction] = useState('');
  const [domain, setDomain] = useState<string>('browser');
  const [entryUrl, setEntryUrl] = useState('');
  const [agent, setAgent] = useState<Agent>('claude');
  const [setupMode, setSetupMode] = useState<AgentMode>('inspect');
  const [runtimeMode, setRuntimeMode] = useState<AgentMode>('act');
  const [recurrence, setRecurrence] = useState<Recurrence>('daily');
  const [dailyAt, setDailyAt] = useState('09:00');
  const [e2e, setE2e] = useState(true);
  const [watchPreset, setWatchPreset] = useState(false);
  const [likeKeywords, setLikeKeywords] = useState('');
  const [commentKeywords, setCommentKeywords] = useState('');
  const [commentStyle, setCommentStyle] = useState('קצר, מקצועי, בעברית או באנגלית לפי הפוסט');
  const [likeNew, setLikeNew] = useState(false);
  const [playbook, setPlaybook] = useState<SchedulePlaybook>(emptyPlaybook());
  const [draftId, setDraftId] = useState<string | null>(null);
  const [setupSessionName, setSetupSessionName] = useState<string | null>(null);
  const [discovering, setDiscovering] = useState(false);
  const [setupBusy, setSetupBusy] = useState(false);
  const [discoverError, setDiscoverError] = useState('');
  const [mapped, setMapped] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const titleRef = useRef<HTMLInputElement>(null);

  const importFromDraft = useCallback((draft: ScheduleSetupDraft) => {
    const applied = applyDraft(draft);
    setTitle(applied.title);
    setInstruction(applied.instruction);
    setDomain(applied.domain);
    setEntryUrl(applied.entryUrl);
    setAgent(applied.agent);
    setRuntimeMode(applied.runtimeMode);
    setPlaybook(applied.playbook);
    setDraftId(draft.id);
    setSetupSessionName(draft.session_name);
    setMapped(true);
  }, []);

  const refreshDraft = useCallback(async () => {
    if (!draftId) return;
    const draft = await fetchSetupDraft(draftId);
    if (draft) importFromDraft(draft);
  }, [draftId, importFromDraft]);

  useEffect(() => {
    void fetchActiveSetupDraft().then((d) => {
      if (d?.status === 'active') importFromDraft(d);
    });
  }, [importFromDraft]);

  useEffect(() => {
    if (!draftId || step !== 'מיפוי') return;
    const t = window.setInterval(() => void refreshDraft(), 4000);
    return () => window.clearInterval(t);
  }, [draftId, step, refreshDraft]);

  useEffect(() => {
    titleRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const applyLinkedInWatch = useCallback(() => {
    const pb = linkedinWatchPlaybook({
      likeKeywords: parseKeywords(likeKeywords),
      commentKeywords: parseKeywords(commentKeywords),
      commentStyle: commentStyle.trim(),
      likeNew,
    });
    setTitle(LINKEDIN_WATCH_TITLE);
    setInstruction(LINKEDIN_WATCH_INSTRUCTION);
    setDomain('browser');
    setEntryUrl(FEED_URL);
    setRuntimeMode('act');
    setE2e(true);
    setRecurrence('every_30');
    setPlaybook(pb);
    setWatchPreset(true);
    setMapped(true);
    setDiscoverError('');
    setError('');
  }, [likeKeywords, commentKeywords, commentStyle, likeNew]);

  const syncWatchPlaybook = useCallback(
    (next: {
      likeKeywords?: string;
      commentKeywords?: string;
      commentStyle?: string;
      likeNew?: boolean;
    }) => {
      const likes = next.likeKeywords ?? likeKeywords;
      const comments = next.commentKeywords ?? commentKeywords;
      const style = next.commentStyle ?? commentStyle;
      const likeAll = next.likeNew ?? likeNew;
      const nextPb = linkedinWatchPlaybook({
        likeKeywords: parseKeywords(likes),
        commentKeywords: parseKeywords(comments),
        commentStyle: style.trim(),
        likeNew: likeAll,
      });
      setPlaybook((prev) => ({
        ...prev,
        ...nextPb,
        watch: { ...prev.watch, ...nextPb.watch },
      }));
    },
    [likeKeywords, commentKeywords, commentStyle, likeNew],
  );

  const runDiscover = useCallback(async () => {
    if (!entryUrl.trim()) {
      setDiscoverError('נדרש URL כניסה');
      return;
    }
    const goal = instruction.trim() || title.trim();
    if (!goal) {
      setDiscoverError('מלא כותרת או הוראות לפני מיפוי');
      return;
    }
    setDiscovering(true);
    setDiscoverError('');
    const result = await discoverSchedulePlaybook({
      entryUrl: entryUrl.trim(),
      goal,
      session: sessionName,
      domain,
      agent,
    });
    setDiscovering(false);
    if (!result.ok) {
      setDiscoverError(result.error ?? 'מיפוי נכשל');
      return;
    }
    if (result.playbook) setPlaybook((prev) => ({ ...prev, ...result.playbook }));
    if (result.instruction && !instruction.trim()) setInstruction(result.instruction);
    setMapped(true);
    setStep('סיום');
  }, [entryUrl, instruction, title, sessionName, domain, agent]);

  const openSetupChat = useCallback(async () => {
    const goal = instruction.trim() || title.trim();
    if (!title.trim() || !goal) {
      setDiscoverError('מלא כותרת והוראות לפני פתיחת צ\'אט הגדרה');
      return;
    }
    if (!entryUrl.trim()) {
      setDiscoverError('נדרש URL כניסה');
      return;
    }
    setSetupBusy(true);
    setDiscoverError('');
    let draft = draftId ? await fetchSetupDraft(draftId) : null;
    if (!draft) {
      draft = await startScheduleSetup({
        title: title.trim(),
        goal,
        entryUrl: entryUrl.trim(),
        domain,
        agent,
        setupMode,
        instruction: instruction.trim() || undefined,
      });
    }
    if (!draft) {
      setSetupBusy(false);
      setDiscoverError('יצירת הגדרה נכשלה');
      return;
    }
    setDraftId(draft.id);
    setSetupSessionName(draft.session_name);
    await bootstrapScheduleSetup(draft.id);
    setSetupBusy(false);
    onOpenSetupChat(draft.session_name, agent);
    onClose();
  }, [
    title, instruction, entryUrl, domain, agent, setupMode, draftId,
    onOpenSetupChat, onClose,
  ]);

  const submit = useCallback(async () => {
    if (!title.trim()) {
      setError('נדרש כותרת');
      return;
    }
    const pb: SchedulePlaybook = {
      version: 1,
      site: playbook.site?.trim() || undefined,
      entry_urls: playbook.entry_urls?.length
        ? playbook.entry_urls
        : entryUrl.trim()
          ? [entryUrl.trim()]
          : [],
      workflow: playbook.workflow ?? [],
      selectors: playbook.selectors ?? {},
      notes: playbook.notes?.trim() || undefined,
      checklist: playbook.checklist ?? [],
      watch: playbook.watch,
    };
    const recurrenceSpec =
      recurrence === 'hourly'
        ? { every_minutes: 60 }
        : recurrence === 'every_30'
          ? { every_minutes: 30 }
          : { daily_at: dailyAt };
    setBusy(true);
    setError('');
    const created = await createSchedule({
      title: title.trim(),
      template: {
        title: title.trim(),
        kind: 'mom_task',
        domain,
        instruction: instruction.trim() || undefined,
        autonomy: e2e ? 'e2e' : 'guarded',
        agent,
        mode: runtimeMode,
        recurrence: recurrenceSpec,
      },
      playbook: pb,
      next_run_at: computeNextRun(recurrence, dailyAt),
      enabled: true,
    });
    setBusy(false);
    if (!created) {
      setError('יצירת התזמון נכשלה');
      return;
    }
    if (draftId) void completeScheduleSetup(draftId);
    onCreated();
    onClose();
  }, [
    title, instruction, domain, recurrence, dailyAt, e2e, playbook, entryUrl,
    agent, runtimeMode, draftId, onClose, onCreated,
  ]);

  const stepIdx = STEPS.indexOf(step);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-3"
      style={{ backdropFilter: 'blur(4px)', backgroundColor: 'rgba(0,0,0,0.45)' }}
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div
        className="flex max-h-[90vh] w-full max-w-md flex-col overflow-hidden rounded-lg border border-line bg-surface-overlay shadow-modal"
        dir="rtl"
      >
        <header className="flex shrink-0 items-center justify-between border-b border-line px-4 py-3">
          <div>
            <h2 className="text-sm font-semibold text-fg">משימה מתוזמנת חדשה</h2>
            <p className="mt-0.5 text-2xs text-fg-subtle">
              שלב {stepIdx + 1}/{STEPS.length}: {step}
            </p>
          </div>
          <button type="button" onClick={onClose} className="rounded p-1 text-fg-subtle hover:bg-surface-raised">
            <X size={14} />
          </button>
        </header>

        <StepDots current={stepIdx} />

        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-3 text-xs">
          {step === 'מטרה' && (
            <>
              <EnginePicker agent={agent} onChange={setAgent} />
              <button
                type="button"
                onClick={applyLinkedInWatch}
                className={[
                  'flex w-full items-center justify-center gap-2 rounded-md border py-2 text-xs font-medium',
                  watchPreset
                    ? 'border-signal bg-signal-subtle text-signal'
                    : 'border-line hover:bg-surface-raised',
                ].join(' ')}
              >
                <Eye size={14} />
                צופה LinkedIn — פיד + התראות, לייק/תגובה לפי כללים
              </button>
              <Field label="כותרת">
                <input ref={titleRef} value={title} onChange={(e) => setTitle(e.target.value)}
                  className="field-input" placeholder="למשל: פוסט לינקדאין שבועי" />
              </Field>
              <Field label="מה לעשות בכל ריצה?">
                <textarea value={instruction} onChange={(e) => setInstruction(e.target.value)} rows={3}
                  className="field-input resize-none" placeholder="תאר את המטרה — זה גם הנחיה לצ'אט ההגדרה" />
              </Field>
              <div className="grid grid-cols-2 gap-2">
                <Field label="domain">
                  <select value={domain} onChange={(e) => setDomain(e.target.value)} className="field-input">
                    {DOMAINS.map((d) => (
                      <option key={d} value={d}>{d}</option>
                    ))}
                  </select>
                </Field>
                <Field label="URL כניסה">
                  <input value={entryUrl} onChange={(e) => setEntryUrl(e.target.value)} className="field-input"
                    placeholder="https://…" dir="ltr" />
                </Field>
              </div>
              {watchPreset && (
                <div className="space-y-2 rounded-md border border-signal/30 bg-signal-subtle/40 p-3">
                  <p className="text-2xs font-medium text-fg">כללי מעורבות אוטומטית</p>
                  <Field label="מילות מפתח ללייק (מופרדות בפסיק)">
                    <input
                      value={likeKeywords}
                      onChange={(e) => {
                        setLikeKeywords(e.target.value);
                        syncWatchPlaybook({ likeKeywords: e.target.value });
                      }}
                      className="field-input"
                      placeholder="hiring, product, AI"
                      dir="ltr"
                    />
                  </Field>
                  <Field label="מילות מפתח לתגובה">
                    <input
                      value={commentKeywords}
                      onChange={(e) => {
                        setCommentKeywords(e.target.value);
                        syncWatchPlaybook({ commentKeywords: e.target.value });
                      }}
                      className="field-input"
                      placeholder="open to work, launch"
                      dir="ltr"
                    />
                  </Field>
                  <Field label="סגנון תגובה">
                    <input
                      value={commentStyle}
                      onChange={(e) => {
                        setCommentStyle(e.target.value);
                        syncWatchPlaybook({ commentStyle: e.target.value });
                      }}
                      className="field-input"
                      placeholder="קצר, מקצועי"
                    />
                  </Field>
                  <label className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={likeNew}
                      onChange={(e) => {
                        setLikeNew(e.target.checked);
                        syncWatchPlaybook({ likeNew: e.target.checked });
                      }}
                      className="accent-signal"
                    />
                    <span>לייק לכל פוסט חדש (לא רק לפי מילות מפתח)</span>
                  </label>
                  <p className="text-2xs text-fg-muted">
                    ה-playbook כבר מוכן — אפשר לדלג על מיפוי. צריך Chrome מחובר ו-LinkedIn מחובר.
                  </p>
                </div>
              )}
              <p className="text-2xs text-fg-subtle">
                מנוע הריצה: <strong>{AGENT_LABELS[agent]}</strong>
                {sessionName ? (
                  <> · טאב דפדפן דרך session <span className="font-mono">{sessionName}</span></>
                ) : (
                  <> · <span className="text-danger">בחר session פעיל לדפדפן</span></>
                )}
              </p>
            </>
          )}

          {step === 'מיפוי' && (
            <>
              <div className="rounded-md border border-signal/30 bg-signal-subtle/40 p-3 space-y-2">
                <p className="text-2xs font-medium text-fg">מומלץ: צ'אט הגדרה ייעודי</p>
                <p className="text-2xs leading-relaxed text-fg-muted">
                  סשן נפרד ({AGENT_LABELS[agent]}) למחקר מעמיק — שאלות, בדיקות,
                  עדכון playbook עד שמוכן.
                </p>
                <Field label="מצב הגדרה">
                  <select value={setupMode} onChange={(e) => setSetupMode(e.target.value as AgentMode)}
                    className="field-input">
                    <option value="inspect">Inspect — קריאה + מיפוי (מומלץ)</option>
                    <option value="plan">Plan — תכנון לפני פעולה</option>
                    <option value="act">Act — יותר אוטונומי</option>
                  </select>
                </Field>
                <button
                  type="button"
                  disabled={setupBusy}
                  onClick={() => void openSetupChat()}
                  className="flex w-full items-center justify-center gap-2 rounded-md bg-signal py-2 text-xs font-semibold text-signal-contrast disabled:opacity-40"
                >
                  {setupBusy ? (
                    <Loader2 size={14} className="animate-spin" />
                  ) : (
                    <MessageSquare size={14} />
                  )}
                  פתח צ'אט הגדרה
                </button>
                {setupSessionName && (
                  <p className="text-2xs text-fg-muted">
                    סשן פעיל: <span className="font-mono">{setupSessionName}</span>
                  </p>
                )}
              </div>

              {draftId && (
                <button type="button" onClick={() => void refreshDraft()}
                  className="flex w-full items-center justify-center gap-1 rounded border border-line py-1.5 text-2xs hover:bg-surface-raised">
                  <RefreshCw size={12} />
                  ייבא עדכונים מהצ'אט
                </button>
              )}

              {mapped && <PlaybookPreview playbook={playbook} onChange={setPlaybook} />}

              <div className="border-t border-line pt-2">
                <p className="mb-2 text-2xs font-medium text-fg-subtle">או: מיפוי מהיר (one-shot)</p>
                <button
                  type="button"
                  disabled={discovering || !entryUrl.trim()}
                  onClick={() => void runDiscover()}
                  className="flex w-full items-center justify-center gap-2 rounded-md border border-line py-2 text-xs hover:bg-surface-raised disabled:opacity-40"
                >
                  {discovering ? (
                    <Loader2 size={14} className="animate-spin" />
                  ) : (
                    <Map size={14} />
                  )}
                  מיפוי מהיר
                </button>
              </div>
              {discoverError && <p className="text-2xs text-danger">{discoverError}</p>}
              <button type="button" onClick={() => setStep('סיום')}
                className="text-2xs text-fg-muted underline hover:text-fg">
                דלג — אמלא playbook ידנית
              </button>
            </>
          )}

          {step === 'סיום' && (
            <>
              <Field label="מצב ריצה (בכל תזמון)">
                <select value={runtimeMode} onChange={(e) => setRuntimeMode(e.target.value as AgentMode)}
                  className="field-input">
                  <option value="act">Act — ביצוע אוטונומי</option>
                  <option value="plan">Plan</option>
                  <option value="inspect">Inspect</option>
                  <option value="test">Test</option>
                </select>
              </Field>
              <div className="grid grid-cols-2 gap-2">
                <Field label="תדירות">
                  <select value={recurrence} onChange={(e) => setRecurrence(e.target.value as Recurrence)}
                    className="field-input">
                    <option value="daily">יומי</option>
                    <option value="hourly">כל שעה</option>
                    <option value="every_30">כל 30 דקות</option>
                  </select>
                </Field>
                {recurrence === 'daily' && (
                  <Field label="שעה">
                    <input type="time" value={dailyAt} onChange={(e) => setDailyAt(e.target.value)}
                      className="field-input" />
                  </Field>
                )}
              </div>
              <label className="flex items-center gap-2">
                <input type="checkbox" checked={e2e} onChange={(e) => setE2e(e.target.checked)} className="accent-signal" />
                <span>E2E — שליחה/פרסום בלי אישור</span>
              </label>
              <p className="text-2xs text-fg-muted">
                מנוע: {AGENT_LABELS[agent]} · ריצה: {runtimeMode}
              </p>
              <PlaybookPreview playbook={playbook} onChange={setPlaybook} editable />
              {error && <p className="rounded bg-danger-subtle px-2 py-1 text-danger">{error}</p>}
            </>
          )}
        </div>

        <footer className="flex shrink-0 items-center justify-between gap-2 border-t border-line px-4 py-3">
          <button type="button" onClick={onClose} className="rounded-md px-3 py-1.5 text-fg-muted hover:bg-surface-raised">
            ביטול
          </button>
          <div className="flex gap-2">
            {stepIdx > 0 && (
              <button type="button" onClick={() => setStep(STEPS[stepIdx - 1])}
                className="flex items-center gap-1 rounded-md border border-line px-3 py-1.5 hover:bg-surface-raised">
                <ChevronRight size={14} />
                הקודם
              </button>
            )}
            {step !== 'סיום' ? (
              <button
                type="button"
                onClick={() => setStep(watchPreset && step === 'מטרה' ? 'סיום' : STEPS[stepIdx + 1])}
                disabled={step === 'מטרה' && !title.trim()}
                className="flex items-center gap-1 rounded-md bg-signal px-3 py-1.5 font-medium text-signal-contrast disabled:opacity-40">
                {watchPreset && step === 'מטרה' ? 'המשך לסיום' : 'הבא'}
                <ChevronLeft size={14} />
              </button>
            ) : (
              <button type="button" disabled={busy || !title.trim()} onClick={() => void submit()}
                className="rounded-md bg-signal px-3 py-1.5 font-medium text-signal-contrast disabled:opacity-40">
                {busy ? 'שומר…' : 'צור תזמון'}
              </button>
            )}
          </div>
        </footer>
      </div>
      <style>{`.field-input{width:100%;border-radius:0.375rem;border:1px solid var(--color-line);background:var(--color-surface);padding:0.5rem 0.75rem;font-size:0.75rem;color:var(--color-fg);outline:none}.field-input:focus{border-color:var(--color-signal)}`}</style>
    </div>
  );
}

function EnginePicker({ agent, onChange }: { agent: Agent; onChange: (a: Agent) => void }) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-2xs font-medium text-fg-muted">מנוע</span>
      <div className="grid flex-1 grid-cols-2 gap-0.5 rounded-md border border-line bg-surface p-0.5">
        {AGENTS.map((a) => (
          <button
            key={a}
            type="button"
            onClick={() => onChange(a)}
            className={[
              'flex-1 rounded px-2 py-1 text-2xs font-medium transition-colors',
              agent === a ? 'bg-signal text-signal-contrast' : 'text-fg-muted hover:text-fg',
            ].join(' ')}
          >
            {AGENT_LABELS[a]}
          </button>
        ))}
      </div>
    </div>
  );
}

function StepDots({ current }: { current: number }) {
  return (
    <div className="flex shrink-0 justify-center gap-2 border-b border-line py-2">
      {STEPS.map((label, i) => (
        <span
          key={label}
          className={[
            'rounded-full px-2 py-0.5 text-2xs font-medium',
            i === current ? 'bg-signal text-signal-contrast' : 'text-fg-subtle',
          ].join(' ')}
        >
          {label}
        </span>
      ))}
    </div>
  );
}

function PlaybookPreview({
  playbook,
  onChange,
  editable = false,
}: {
  playbook: SchedulePlaybook;
  onChange: (p: SchedulePlaybook) => void;
  editable?: boolean;
}) {
  const workflow = (playbook.workflow ?? []).join('\n');
  const selectors = JSON.stringify(playbook.selectors ?? {}, null, 2);
  return (
    <div className="space-y-2 rounded-md border border-line bg-surface-raised p-2">
      <p className="text-2xs font-medium text-fg-muted">Playbook</p>
      {playbook.site && <p className="text-2xs text-fg">אתר: {playbook.site}</p>}
      {playbook.watch && (
        <p className="text-2xs text-fg-muted">
          Watch: {playbook.watch.allow_auto_engage ? 'auto-engage' : 'read-only'}
          {playbook.watch.like_new ? ' · like-new' : ''}
          {(playbook.watch.like_keywords?.length ?? 0) > 0
            ? ` · like: ${playbook.watch.like_keywords?.join(', ')}`
            : ''}
          {(playbook.watch.comment_keywords?.length ?? 0) > 0
            ? ` · comment: ${playbook.watch.comment_keywords?.join(', ')}`
            : ''}
        </p>
      )}
      {editable ? (
        <>
          <Field label="שלבים">
            <textarea
              value={workflow}
              onChange={(e) =>
                onChange({
                  ...playbook,
                  workflow: e.target.value.split('\n').map((l) => l.trim()).filter(Boolean),
                })
              }
              rows={3}
              className="field-input resize-none font-mono text-2xs"
            />
          </Field>
          <Field label="Selectors">
            <textarea
              value={selectors}
              onChange={(e) => {
                try {
                  onChange({ ...playbook, selectors: JSON.parse(e.target.value) as Record<string, string> });
                } catch {
                  /* typing */
                }
              }}
              rows={3}
              className="field-input resize-none font-mono text-2xs"
              dir="ltr"
            />
          </Field>
          <Field label="הערות">
            <textarea
              value={playbook.notes ?? ''}
              onChange={(e) => onChange({ ...playbook, notes: e.target.value })}
              rows={2}
              className="field-input resize-none text-2xs"
            />
          </Field>
        </>
      ) : (
        <>
          {(playbook.workflow ?? []).length > 0 && (
            <ul className="list-inside list-decimal text-2xs text-fg-muted">
              {(playbook.workflow ?? []).map((s, i) => (
                <li key={i}>{s}</li>
              ))}
            </ul>
          )}
          {Object.keys(playbook.selectors ?? {}).length > 0 && (
            <pre className="overflow-x-auto rounded bg-surface p-1.5 font-mono text-2xs" dir="ltr">
              {selectors}
            </pre>
          )}
        </>
      )}
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-0.5 block text-2xs font-medium text-fg-muted">{label}</span>
      {children}
    </label>
  );
}
