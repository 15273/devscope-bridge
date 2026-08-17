/**
 * WhatsAppCockpit — "Waiting on you" queue + WhatsApp Assistant.
 *
 * Rendered when view === 'whatsapp'. RTL/Hebrew-first.
 * Two-tab toggle: "ממתינים" (nudge queue) | "עוזר" (assistant chat).
 * Each NudgeCard exposes "התייעץ" which switches to the assistant tab
 * and scopes it to that chat. Settings panel collapsible from the queue tab.
 */
import { useState, useCallback } from 'react';
import { Settings, RefreshCw } from 'lucide-react';
import { useCockpit } from './useCockpit';
import { NudgeCard } from './NudgeCard';
import { CockpitSettings } from './CockpitSettings';
import { AssistChat, type ScopedChat } from './AssistChat';

type Tab = 'queue' | 'assist';

interface WhatsAppCockpitProps {
  sessionName: string | null;
}

export function WhatsAppCockpit({ sessionName }: WhatsAppCockpitProps) {
  const {
    nudges,
    settings,
    loading,
    error,
    health,
    draft,
    send,
    markHandled,
    mute,
    saveSettings,
    refreshHealth,
    ask,
  } = useCockpit(sessionName);
  const [showSettings, setShowSettings] = useState(false);
  const [tab, setTab] = useState<Tab>('queue');
  const [scopedChat, setScopedChat] = useState<ScopedChat | null>(null);

  // Switch to assistant tab scoped to a specific chat from NudgeCard "התייעץ"
  const handleConsult = useCallback((chatId: string, name: string) => {
    setScopedChat({ chatId, name });
    setTab('assist');
    setShowSettings(false);
  }, []);

  const handleClearScope = useCallback(() => {
    setScopedChat(null);
  }, []);

  const handleTabSwitch = useCallback((t: Tab) => {
    setTab(t);
    if (t === 'queue') setShowSettings(false);
  }, []);

  return (
    <div dir="rtl" className="flex min-h-0 flex-1 flex-col overflow-hidden">
      {/* Header */}
      <div className="flex shrink-0 items-center gap-2 border-b border-line bg-surface-raised px-3 py-2.5">
        {/* Tab toggle */}
        <div className="flex flex-1 items-center gap-1 rounded-md border border-line bg-surface p-0.5">
          <button
            type="button"
            onClick={() => handleTabSwitch('queue')}
            className={[
              'flex h-6 flex-1 items-center justify-center rounded text-xs font-medium transition-colors duration-fast ease-tool',
              tab === 'queue'
                ? 'bg-signal text-signal-contrast'
                : 'text-fg-muted hover:text-fg',
            ].join(' ')}
          >
            ממתינים
            {nudges.length > 0 && (
              <span
                className={[
                  'mr-1.5 inline-flex h-4 min-w-[16px] items-center justify-center rounded-full px-1 text-2xs font-semibold',
                  tab === 'queue'
                    ? 'bg-white/25 text-signal-contrast'
                    : 'bg-signal text-signal-contrast',
                ].join(' ')}
              >
                {nudges.length}
              </span>
            )}
          </button>
          <button
            type="button"
            onClick={() => handleTabSwitch('assist')}
            className={[
              'flex h-6 flex-1 items-center justify-center rounded text-xs font-medium transition-colors duration-fast ease-tool',
              tab === 'assist'
                ? 'bg-signal text-signal-contrast'
                : 'text-fg-muted hover:text-fg',
            ].join(' ')}
          >
            עוזר
          </button>
        </div>

        {/* Settings toggle — only in queue tab */}
        {tab === 'queue' && (
          <button
            type="button"
            onClick={() => setShowSettings((v) => !v)}
            aria-pressed={showSettings}
            className={[
              'flex h-7 w-7 items-center justify-center rounded-md transition-colors duration-fast ease-tool',
              showSettings
                ? 'bg-signal-subtle text-signal'
                : 'text-fg-muted hover:bg-surface-overlay hover:text-fg',
            ].join(' ')}
            aria-label="הגדרות"
          >
            <Settings size={15} />
          </button>
        )}

        {tab === 'assist' && (
          <button
            type="button"
            onClick={() => void refreshHealth()}
            className="flex h-7 w-7 items-center justify-center rounded-md text-fg-muted transition-colors duration-fast ease-tool hover:bg-surface-overlay hover:text-fg"
            aria-label="רענן חיבור WhatsApp"
            title={
              health?.live.ok
                ? `WhatsApp מחובר (${health.live.sample_chats ?? 0} צ'אטים)`
                : 'WhatsApp לא מחובר — פתח web.whatsapp.com'
            }
          >
            <RefreshCw size={14} className={health?.live.ok ? 'text-signal' : ''} />
          </button>
        )}
      </div>

      {tab === 'assist' && health && !health.live.ok && (
        <div className="shrink-0 border-b border-line bg-danger-subtle px-3 py-1.5">
          <p className="text-2xs text-danger">
            WhatsApp לא מחובר — פתח web.whatsapp.com בטאב מקושר ל-{sessionName ?? 'DevScope'}
          </p>
        </div>
      )}

      {/* Settings panel (collapsible, queue tab only) */}
      {tab === 'queue' && showSettings && (
        <div className="shrink-0 border-b border-line p-3">
          <CockpitSettings
            settings={settings}
            onSave={saveSettings}
            onClose={() => setShowSettings(false)}
          />
        </div>
      )}

      {/* Queue tab */}
      {tab === 'queue' && (
        <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto p-3">
          {loading && <LoadingSkeleton />}

          {!loading && error && (
            <div className="flex flex-col items-center gap-2 rounded-md bg-danger-subtle p-3 text-center">
              <p className="text-xs font-medium text-danger">שגיאה בטעינת הנאגים</p>
              <p className="text-2xs text-fg-muted">{error}</p>
            </div>
          )}

          {!loading && !error && nudges.length === 0 && (
            <div className="flex flex-1 flex-col items-center justify-center gap-2 py-12 text-center">
              <span className="text-3xl" aria-hidden="true">
                🎉
              </span>
              <p className="text-sm font-medium text-fg">אין הודעות שמחכות לך</p>
              <p className="text-xs text-fg-muted">כל הכבוד — עניתָ לכולם!</p>
            </div>
          )}

          {!loading &&
            !error &&
            nudges.map((nudge) => (
              <NudgeCard
                key={nudge.chat_id}
                nudge={nudge}
                onMarkHandled={markHandled}
                onMute={mute}
                onDraft={draft}
                onSend={send}
                onConsult={handleConsult}
              />
            ))}
        </div>
      )}

      {/* Assistant tab */}
      {tab === 'assist' && (
        <AssistChat
          ask={ask}
          send={send}
          scopedChat={scopedChat}
          onClearScope={handleClearScope}
        />
      )}
    </div>
  );
}

// ── Loading skeleton ──────────────────────────────────────────────────────────

function LoadingSkeleton() {
  return (
    <>
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          className="flex animate-pulse flex-col gap-2 rounded-md border border-line bg-surface p-3"
        >
          <div className="flex items-start gap-2.5">
            <div className="h-9 w-9 shrink-0 rounded-full bg-surface-overlay" />
            <div className="flex-1 space-y-1.5">
              <div className="h-3 w-24 rounded bg-surface-overlay" />
              <div className="h-2.5 w-40 rounded bg-surface-overlay" />
            </div>
            <div className="h-2.5 w-12 rounded bg-surface-overlay" />
          </div>
          <div className="mt-1 flex gap-1.5">
            <div className="h-7 w-20 rounded-md bg-surface-overlay" />
            <div className="h-7 w-14 rounded-md bg-surface-overlay" />
            <div className="h-7 w-12 rounded-md bg-surface-overlay" />
          </div>
        </div>
      ))}
    </>
  );
}
