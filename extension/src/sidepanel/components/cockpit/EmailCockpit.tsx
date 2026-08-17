/**
 * EmailCockpit — inbox thread list + reader (Gmail via bridge /gm/*).
 */
import { useState, useCallback } from 'react';
import { Mail, RefreshCw, Search } from 'lucide-react';
import { CockpitShell } from '../CockpitShell';
import { AiAssistPanel } from '../AiAssistPanel';
import { useGmail } from './useGmail';

const QUICK_FILTERS: { label: string; q: string }[] = [
  { label: 'דואר נכנס', q: 'in:inbox' },
  { label: 'לא נקרא', q: 'is:unread in:inbox' },
  { label: 'חשוב', q: 'is:important' },
  { label: 'נשלח', q: 'in:sent' },
];

function threadPreview(snippet?: string): string {
  if (!snippet) return '(ללא תצוגה מקדימה)';
  return snippet.length > 80 ? `${snippet.slice(0, 80)}…` : snippet;
}

export function EmailCockpit() {
  const {
    query,
    setQuery,
    threads,
    selectedId,
    threadDetail,
    health,
    loading,
    detailLoading,
    error,
    refreshThreads,
    loadThread,
  } = useGmail();

  const [assistOutput, setAssistOutput] = useState('');
  const needsAuth = health && !health.token_configured;

  const buildContext = useCallback(() => {
    if (!threadDetail) return '';
    const lines = [
      `נושא: ${threadDetail.subject}`,
      ...threadDetail.messages.map(
        (m) => `מ: ${m.from}\nתאריך: ${m.date}\n${m.snippet}`,
      ),
    ];
    return lines.join('\n\n---\n\n');
  }, [threadDetail]);

  const copyContext = useCallback(async () => {
    const text = buildContext();
    if (!text) {
      setAssistOutput('בחר שרשור כדי להעתיק הקשר.');
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
      setAssistOutput('הקשר הועתק — הדבק בצ\'אט לסיכום / טיוטה.');
    } catch {
      setAssistOutput(text.slice(0, 500));
    }
  }, [buildContext]);

  const listPane = (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="shrink-0 border-b border-line p-2">
        <div className="flex flex-wrap gap-1">
          {QUICK_FILTERS.map((f) => (
            <button
              key={f.q}
              type="button"
              onClick={() => setQuery(f.q)}
              className={[
                'rounded px-1.5 py-0.5 text-2xs transition-colors',
                query === f.q
                  ? 'bg-signal text-signal-contrast'
                  : 'bg-surface-overlay text-fg-muted hover:text-fg',
              ].join(' ')}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {loading && threads.length === 0 ? (
          <p className="p-2 text-2xs text-fg-muted">טוען…</p>
        ) : threads.length === 0 ? (
          <p className="p-2 text-2xs text-fg-muted">אין שרשורים.</p>
        ) : (
          <ul>
            {threads.map((t) => {
              const active = selectedId === t.id;
              return (
                <li key={t.id}>
                  <button
                    type="button"
                    onClick={() => void loadThread(t.id)}
                    className={[
                      'w-full border-b border-line px-2 py-2 text-start text-2xs transition-colors',
                      active
                        ? 'bg-signal-subtle text-fg'
                        : 'text-fg-muted hover:bg-surface-overlay hover:text-fg',
                    ].join(' ')}
                  >
                    {threadPreview(t.snippet)}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );

  const readerPane = (
    <div className="flex min-h-0 flex-1 flex-col p-3">
      {detailLoading ? (
        <p className="text-xs text-fg-muted">טוען שרשור…</p>
      ) : !threadDetail ? (
        <p className="text-xs text-fg-muted">בחר שרשור מהרשימה.</p>
      ) : (
        <>
          <h2 className="text-sm font-semibold text-fg">{threadDetail.subject || '(ללא נושא)'}</h2>
          <ul className="mt-3 space-y-3">
            {threadDetail.messages.map((m, i) => (
              <li
                key={`${m.date}-${i}`}
                className="rounded-lg border border-line bg-surface-raised px-3 py-2"
              >
                <div className="text-2xs font-medium text-fg">{m.from}</div>
                <div className="text-2xs text-fg-subtle">{m.date}</div>
                <p className="mt-1 whitespace-pre-wrap text-xs text-fg-muted">{m.snippet}</p>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );

  const assistPane = (
    <div className="flex flex-1 flex-col">
      <AiAssistPanel
        actions={[
          { label: 'העתק הקשר לצ\'אט', onClick: () => void copyContext() },
          { label: 'רענן', onClick: () => void refreshThreads() },
        ]}
      />
      {assistOutput && (
        <p className="px-2 pb-2 text-2xs text-fg-muted">{assistOutput}</p>
      )}
    </div>
  );

  return (
    <div dir="rtl" className="flex min-h-0 flex-1 flex-col overflow-hidden">
      <div className="flex shrink-0 items-center justify-between border-b border-line bg-surface-raised px-3 py-2">
        <div className="flex items-center gap-2 text-sm font-semibold text-fg">
          <Mail size={16} className="text-signal" />
          מייל
        </div>
        <div className="flex items-center gap-1">
          <div className="flex items-center gap-1 rounded-md border border-line bg-surface px-2 py-0.5">
            <Search size={12} className="text-fg-subtle" />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') void refreshThreads();
              }}
              className="w-24 bg-transparent text-2xs text-fg outline-none"
              aria-label="חיפוש Gmail"
            />
          </div>
          <button
            type="button"
            onClick={() => void refreshThreads()}
            className="flex h-7 w-7 items-center justify-center rounded-md text-fg-muted transition-colors hover:bg-surface-overlay hover:text-fg"
            aria-label="רענן"
          >
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          </button>
        </div>
      </div>

      {needsAuth && (
        <div className="mx-3 mt-3 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-fg">
          חיבור Gmail נדרש. הרץ:
          <code className="mt-1 block break-all rounded bg-surface px-2 py-1 text-2xs">
            python -m devscope_bridge.gmail.authorize_gmail
          </code>
        </div>
      )}

      {error && (
        <div className="mx-3 mt-3 rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-200">
          {error}
        </div>
      )}

      <CockpitShell list={listPane} reader={readerPane} assist={assistPane} />
    </div>
  );
}
