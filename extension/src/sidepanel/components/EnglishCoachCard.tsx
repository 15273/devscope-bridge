/**
 * EnglishCoachCard — dedicated card for the English Coach side-query
 * (role === 'ask', askKind === 'english_coach').
 *
 * Distinct from ParallelAskBubble: the lesson content is in the user's native
 * language, so Hebrew/Arabic get proper RTL rendering. The card is collapsible
 * after completion, shows a streaming cursor while the lesson arrives, and
 * surfaces an error state if the coach fails.
 *
 * Design: Graphite hand-CSS tokens — no Tailwind (this extension does NOT use
 * Tailwind). Contrast rule: never dark-on-dark or light-on-light in any theme.
 */
import { useState } from 'react';
import type { ChatMessage } from '../store/sessionStore';
import { MarkdownMessage } from './MarkdownMessage';

interface EnglishCoachCardProps {
  message: ChatMessage;
}

/** Languages that read right-to-left. */
const RTL_LANGS = new Set(['he', 'ar', 'fa', 'ur']);

function isRtlLang(lang: string): boolean {
  return RTL_LANGS.has(lang.split('-')[0].toLowerCase());
}

/** Read coachLang once from storage (synchronous best-effort from sessionStorage cache). */
function useCoachLang(): string {
  // We can't call async chrome.storage here, so we read from a module-level
  // cache that gets populated on first Settings load. Defaults to 'he'.
  return getCoachLangSync();
}

let _cachedLang = 'he';

/** Called by Settings when prefs change — keeps the card RTL without a page reload. */
export function setCoachLangCache(lang: string): void {
  _cachedLang = lang;
}

function getCoachLangSync(): string {
  return _cachedLang;
}

// Hydrate the cache once on module load from chrome.storage (fire-and-forget).
if (typeof chrome !== 'undefined' && chrome.storage?.local) {
  chrome.storage.local
    .get('coachPrefs')
    .then((result) => {
      const stored = result['coachPrefs'] as { lang?: string } | undefined;
      if (stored?.lang) _cachedLang = stored.lang;
    })
    .catch(() => {});
}

function StreamingCursor() {
  return (
    <span
      className="ml-0.5 inline-block font-mono text-signal animate-cursor-pulse"
      aria-hidden
    >
      ▌
    </span>
  );
}

function CollapseChevron({ open }: { open: boolean }) {
  return (
    <svg
      width="12"
      height="12"
      viewBox="0 0 12 12"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      style={{
        transform: open ? 'rotate(90deg)' : 'rotate(0deg)',
        transition: 'transform var(--duration-fast) var(--ease-tool)',
        flexShrink: 0,
      }}
    >
      <path d="M4 2l4 4-4 4" />
    </svg>
  );
}

export function EnglishCoachCard({ message }: EnglishCoachCardProps) {
  const [collapsed, setCollapsed] = useState(false);
  const lang = useCoachLang();
  const mixedBidi = isRtlLang(lang);

  const failed = Boolean(message.askDone && message.askOk === false);
  const isDone = Boolean(message.askDone && message.askOk !== false);
  const isStreaming = message.isStreaming;

  const headerLabel = '📘 English coach';

  return (
    <div
      dir="auto"
      className={mixedBidi ? 'bidi-plaintext text-start' : undefined}
      style={{
        margin: '4px 0',
        borderRadius: '8px',
        border: `1px dashed ${failed ? 'color-mix(in srgb, var(--warning) 55%, transparent)' : 'color-mix(in srgb, var(--coach-accent, #7c6af0) 55%, transparent)'}`,
        backgroundColor: 'var(--surface-raised)',
        padding: '10px 12px',
      }}
    >
      {/* Header row */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '6px',
          marginBottom: collapsed && isDone ? 0 : '6px',
        }}
      >
        {/* Collapse button — only when done and has content */}
        {isDone && message.text ? (
          <button
            type="button"
            onClick={() => setCollapsed((v) => !v)}
            aria-label={collapsed ? 'Expand English coach lesson' : 'Collapse English coach lesson'}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '5px',
              background: 'none',
              border: 'none',
              padding: 0,
              cursor: 'pointer',
              color: 'var(--coach-accent-label, #7c6af0)',
              fontSize: '11px',
              fontWeight: 600,
              lineHeight: 1,
            }}
          >
            <CollapseChevron open={!collapsed} />
            {headerLabel}
          </button>
        ) : (
          <span
            style={{
              fontSize: '11px',
              fontWeight: 600,
              color: failed ? 'var(--warning)' : 'var(--coach-accent-label, #7c6af0)',
            }}
          >
            {headerLabel}
          </span>
        )}

        {/* Status badges */}
        {failed && (
          <span
            style={{
              borderRadius: '4px',
              background: 'var(--warning-subtle)',
              padding: '2px 6px',
              fontSize: '10px',
              fontWeight: 500,
              color: 'var(--warning)',
            }}
          >
            failed
          </span>
        )}
        {isDone && !failed && (
          <span
            style={{
              borderRadius: '4px',
              background: 'var(--success-subtle)',
              padding: '2px 6px',
              fontSize: '10px',
              fontWeight: 500,
              color: 'var(--success)',
            }}
          >
            done
          </span>
        )}
      </div>

      {/* Body — hidden when collapsed */}
      {!collapsed && (
        <CardBody message={message} mixedBidi={mixedBidi} isStreaming={isStreaming} failed={failed} />
      )}
    </div>
  );
}

interface CardBodyProps {
  message: ChatMessage;
  mixedBidi: boolean;
  isStreaming: boolean;
  failed: boolean;
}

function CardBody({ message, mixedBidi, isStreaming, failed }: CardBodyProps) {
  if (failed) {
    return (
      <p
        dir="auto"
        style={{
          fontSize: '12px',
          color: 'var(--warning)',
          margin: 0,
          lineHeight: 1.5,
        }}
      >
        The English coach encountered an error and could not complete the lesson.
      </p>
    );
  }

  if (!message.text && isStreaming) {
    return <StreamingCursor />;
  }

  if (!message.text) {
    return null;
  }

  return (
    <div
      dir="auto"
      className={mixedBidi ? 'bidi-plaintext text-start' : undefined}
      style={{
        fontSize: '13px',
        color: 'var(--fg)',
        lineHeight: 1.6,
      }}
    >
      <MarkdownMessage text={message.text} isStreaming={isStreaming} mixedBidi={mixedBidi} />
      {isStreaming && <StreamingCursor />}
    </div>
  );
}
