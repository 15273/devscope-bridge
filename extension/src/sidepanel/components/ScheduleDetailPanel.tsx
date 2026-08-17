/**
 * ScheduleDetailPanel — view/edit playbook memory for a recurring schedule.
 */
import { useCallback, useEffect, useState } from 'react';
import { ArrowRight, Loader2, Save } from 'lucide-react';
import {
  parseSchedulePlaybook,
  patchSchedule,
  patchSchedulePlaybook,
  type ScheduleEntry,
  type SchedulePlaybook,
} from '../bridge';

interface ScheduleDetailPanelProps {
  schedule: ScheduleEntry;
  onClose: () => void;
  onSaved: () => void;
}

export function ScheduleDetailPanel({ schedule, onClose, onSaved }: ScheduleDetailPanelProps) {
  const pb0 = parseSchedulePlaybook(schedule.playbook);
  const [site, setSite] = useState(pb0.site ?? '');
  const [entryUrls, setEntryUrls] = useState((pb0.entry_urls ?? []).join('\n'));
  const [workflow, setWorkflow] = useState((pb0.workflow ?? []).join('\n'));
  const [selectorsJson, setSelectorsJson] = useState(JSON.stringify(pb0.selectors ?? {}, null, 2));
  const [notes, setNotes] = useState(pb0.notes ?? '');
  const [enabled, setEnabled] = useState(Boolean(schedule.enabled ?? true));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const pb = parseSchedulePlaybook(schedule.playbook);
    setSite(pb.site ?? '');
    setEntryUrls((pb.entry_urls ?? []).join('\n'));
    setWorkflow((pb.workflow ?? []).join('\n'));
    setSelectorsJson(JSON.stringify(pb.selectors ?? {}, null, 2));
    setNotes(pb.notes ?? '');
    setEnabled(Boolean(schedule.enabled ?? true));
  }, [schedule]);

  const save = useCallback(async () => {
    let selectors: SchedulePlaybook['selectors'] = {};
    try {
      selectors = JSON.parse(selectorsJson) as SchedulePlaybook['selectors'];
    } catch {
      setError('JSON selectors לא תקין');
      return;
    }
    setBusy(true);
    setError(null);
    const patch: Partial<SchedulePlaybook> = {
      site: site.trim() || undefined,
      entry_urls: entryUrls.split('\n').map((l) => l.trim()).filter(Boolean),
      workflow: workflow.split('\n').map((l) => l.trim()).filter(Boolean),
      selectors,
      notes: notes.trim() || undefined,
    };
    const okPb = await patchSchedulePlaybook(schedule.id, patch);
    const okSched = await patchSchedule(schedule.id, { enabled });
    setBusy(false);
    if (!okPb || !okSched) {
      setError('שמירה נכשלה');
      return;
    }
    onSaved();
  }, [site, entryUrls, workflow, selectorsJson, notes, enabled, schedule.id, onSaved]);

  const pb = parseSchedulePlaybook(schedule.playbook);

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg border border-line bg-surface-overlay/30">
      <header className="flex shrink-0 items-center gap-2 border-b border-line px-2.5 py-2">
        <button type="button" onClick={onClose}
          className="flex h-7 w-7 items-center justify-center rounded-md text-fg-muted hover:bg-surface-overlay">
          <ArrowRight size={16} />
        </button>
        <h3 className="min-w-0 flex-1 truncate text-sm font-semibold text-fg">{schedule.title}</h3>
        <button type="button" disabled={busy} onClick={() => void save()}
          className="flex items-center gap-1 rounded-md bg-signal px-2 py-1 text-2xs text-signal-contrast disabled:opacity-50">
          {busy ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
          שמור
        </button>
      </header>
      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-2.5 text-xs" dir="rtl">
        <Meta label="ריצה הבאה" value={schedule.next_run_at ?? '—'} />
        <Meta label="ריצה אחרונה" value={schedule.last_run_at ?? '—'} />
        {pb.last_success_at && <Meta label="הצלחה אחרונה" value={pb.last_success_at} />}
        {(pb.learned_from_runs ?? 0) > 0 && (
          <Meta label="עדכוני playbook" value={String(pb.learned_from_runs)} />
        )}
        <label className="flex items-center gap-2 py-1">
          <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} className="accent-signal" />
          <span>פעיל</span>
        </label>
        <p className="text-2xs text-fg-subtle">
          ה-agent ישתמש ב-playbook בכל ריצה. עדכן selectors כשהדף משתנה — לא צריך לגלות מחדש.
        </p>
        <TextField label="אתר" value={site} onChange={setSite} />
        <TextArea label="URLs כניסה" value={entryUrls} onChange={setEntryUrls} rows={2} />
        <TextArea label="שלבים" value={workflow} onChange={setWorkflow} rows={5} mono />
        <TextArea label="Selectors (JSON)" value={selectorsJson} onChange={setSelectorsJson} rows={6} mono />
        <TextArea label="הערות" value={notes} onChange={setNotes} rows={3} />
        {error && <p className="text-danger">{error}</p>}
      </div>
    </div>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-2">
      <span className="text-fg-subtle">{label}</span>
      <span className="font-mono text-fg">{value}</span>
    </div>
  );
}

function TextField({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <label className="block">
      <span className="mb-0.5 block text-2xs text-fg-subtle">{label}</span>
      <input value={value} onChange={(e) => onChange(e.target.value)}
        className="w-full rounded border border-line bg-surface px-2 py-1.5 text-xs text-fg outline-none focus:border-signal" />
    </label>
  );
}

function TextArea({
  label, value, onChange, rows, mono,
}: {
  label: string; value: string; onChange: (v: string) => void; rows: number; mono?: boolean;
}) {
  return (
    <label className="block">
      <span className="mb-0.5 block text-2xs text-fg-subtle">{label}</span>
      <textarea value={value} onChange={(e) => onChange(e.target.value)} rows={rows}
        className={`w-full resize-none rounded border border-line bg-surface px-2 py-1.5 text-xs text-fg outline-none focus:border-signal ${mono ? 'font-mono text-2xs' : ''}`} />
    </label>
  );
}
