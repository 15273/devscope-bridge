/**
 * NudgeCard — one "waiting on you" chat in the Copilot queue.
 *
 * Shows: circular avatar (initials), chat name, group badge, last-message
 * preview (truncated), relative age, and an action row.
 * "נסח תשובה" triggers AI drafting and expands DraftComposer inline.
 */
import { useState, useCallback } from 'react';
import type { Nudge, UseCockpitReturn } from './useCockpit';
import { DraftComposer } from './DraftComposer';

interface NudgeCardProps {
  nudge: Nudge;
  onMarkHandled: UseCockpitReturn['markHandled'];
  onMute: UseCockpitReturn['mute'];
  onDraft: UseCockpitReturn['draft'];
  onSend: UseCockpitReturn['send'];
  onConsult?: (chatId: string, name: string) => void;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function getInitials(name: string): string {
  const parts = name.trim().split(/\s+/);
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

function relativeAge(sinceTs: number): string {
  const diffMs = Date.now() - sinceTs * 1000;
  const diffH = Math.floor(diffMs / 3_600_000);
  const diffM = Math.floor(diffMs / 60_000);
  if (diffH >= 24) {
    const days = Math.floor(diffH / 24);
    return `לפני כ-${days} ימים`;
  }
  if (diffH >= 1) return `לפני כ-${diffH} שעות`;
  if (diffM >= 1) return `לפני כ-${diffM} דקות`;
  return 'לפני מעט';
}

// Stable avatar colour derived from chat_id so each contact gets a consistent hue
const AVATAR_COLOURS = [
  'bg-blue-500',
  'bg-purple-500',
  'bg-emerald-500',
  'bg-rose-500',
  'bg-amber-500',
  'bg-indigo-500',
  'bg-teal-500',
  'bg-orange-500',
];

function avatarColour(chatId: string): string {
  let h = 0;
  for (let i = 0; i < chatId.length; i++) h = (h * 31 + chatId.charCodeAt(i)) & 0xfffffff;
  return AVATAR_COLOURS[h % AVATAR_COLOURS.length];
}

// ── Component ─────────────────────────────────────────────────────────────────

export function NudgeCard({ nudge, onMarkHandled, onMute, onDraft, onSend, onConsult }: NudgeCardProps) {
  const [composerCandidates, setComposerCandidates] = useState<string[] | null>(null);
  const [draftLoading, setDraftLoading] = useState(false);
  const [draftError, setDraftError] = useState<string | null>(null);

  const handleDraft = useCallback(async () => {
    setDraftLoading(true);
    setDraftError(null);
    setComposerCandidates(null);
    try {
      const candidates = await onDraft(nudge.chat_id);
      setComposerCandidates(candidates);
    } catch (e) {
      setDraftError(e instanceof Error ? e.message : String(e));
    } finally {
      setDraftLoading(false);
    }
  }, [nudge.chat_id, onDraft]);

  const handleSend = useCallback(
    async (text: string) => {
      await onSend(nudge.chat_id, text);
      setComposerCandidates(null);
    },
    [nudge.chat_id, onSend],
  );

  const colour = avatarColour(nudge.chat_id);

  return (
    <div
      dir="rtl"
      className="flex flex-col gap-2 rounded-md border border-line bg-surface p-3 shadow-tool"
    >
      {/* Top row: avatar + name + age */}
      <div className="flex items-start gap-2.5">
        {/* Avatar */}
        <div
          className={[
            'flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-xs font-semibold text-white',
            colour,
          ].join(' ')}
          aria-hidden="true"
        >
          {getInitials(nudge.name)}
        </div>

        {/* Name + preview */}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span className="truncate text-sm font-semibold text-fg">{nudge.name}</span>
            {nudge.is_group && (
              <span className="shrink-0 rounded-sm border border-line px-1 py-0 text-2xs text-fg-muted">
                קבוצה
              </span>
            )}
          </div>
          <p className="mt-0.5 truncate text-xs text-fg-muted">{nudge.last_msg_preview}</p>
        </div>

        {/* Relative age */}
        <span className="shrink-0 text-2xs text-fg-subtle">{relativeAge(nudge.since_ts)}</span>
      </div>

      {/* Draft error */}
      {draftError && (
        <p className="rounded-sm bg-danger-subtle px-2 py-1 text-2xs text-danger">
          {draftError}
        </p>
      )}

      {/* Inline composer (appears after draft) */}
      {composerCandidates !== null && (
        <DraftComposer
          chatName={nudge.name}
          chatId={nudge.chat_id}
          candidates={composerCandidates}
          onSend={handleSend}
          onClose={() => setComposerCandidates(null)}
        />
      )}

      {/* Action row */}
      <div className="flex items-center gap-1.5 pt-0.5">
        {/* Primary: draft */}
        <button
          type="button"
          disabled={draftLoading}
          onClick={handleDraft}
          className="flex h-7 items-center gap-1 rounded-md bg-signal px-2.5 text-xs font-medium text-signal-contrast transition-colors duration-fast ease-tool hover:bg-signal-hover disabled:cursor-wait disabled:opacity-60"
        >
          {draftLoading ? 'טוען…' : 'נסח תשובה'}
        </button>

        {/* Secondary: handled */}
        <button
          type="button"
          onClick={() => void onMarkHandled(nudge.chat_id)}
          className="flex h-7 items-center rounded-md border border-line bg-surface px-2.5 text-xs font-medium text-fg transition-colors duration-fast ease-tool hover:bg-surface-overlay"
        >
          טופל
        </button>

        {/* Subtle: mute */}
        <button
          type="button"
          onClick={() => void onMute(nudge.chat_id)}
          className="flex h-7 items-center rounded-md px-2.5 text-xs font-medium text-fg-muted transition-colors duration-fast ease-tool hover:bg-surface-overlay hover:text-fg"
        >
          השתק
        </button>

        {/* Consult assistant */}
        {onConsult && (
          <button
            type="button"
            onClick={() => onConsult(nudge.chat_id, nudge.name)}
            className="mr-auto flex h-7 items-center rounded-md border border-line bg-surface px-2.5 text-xs font-medium text-fg-muted transition-colors duration-fast ease-tool hover:bg-surface-overlay hover:text-fg"
          >
            התייעץ
          </button>
        )}
      </div>
    </div>
  );
}
