/**
 * ToolCallRow — one visually distinct row per tool call (running → done/error).
 *
 * Extracted out of Chat.tsx (was a near-invisible inline `ToolRow` styled as
 * tiny 2xs gray text). Renders both CLI tool-call rows (Bash/Read/Write/MCP,
 * driven by the TOOL_CALL reducer keyed on call_id) and the client-driven
 * browser-control round-trip rows (TOOL_ACTIVITY, keyed on actionId) through
 * the same component, so there is one visual language for "a tool ran."
 */
import { useEffect, useState } from 'react';
import {
  AlertTriangle,
  CalendarDays,
  Check,
  ChevronDown,
  FileText,
  Globe,
  Link2,
  Mail,
  Megaphone,
  MessageCircle,
  Pencil,
  Search,
  Terminal,
  Users,
  Wrench,
  type LucideIcon,
} from 'lucide-react';
import type { ChatMessage } from '../store/sessionStore';
import { MixedBidiText } from '../utils/mixedBidiText';

const ICON_BY_KEYWORD: [RegExp, LucideIcon][] = [
  [/^bash$/i, Terminal],
  [/^read$/i, FileText],
  [/^(write|edit|multiedit)$/i, Pencil],
  [/^(grep|glob)$/i, Search],
  [/^task$/i, Users],
  [/^webfetch$/i, Link2],
  [/whatsapp|^wa_/i, MessageCircle],
  [/gmail|^gm_/i, Mail],
  [/calendar|^cal_/i, CalendarDays],
  [/meta.?ads|^meta_/i, Megaphone],
  [/task-control|^schedule_|^task_/i, Users],
  [/browser/i, Globe],
];

function getToolIcon(tool?: string): LucideIcon {
  if (!tool) return Wrench;
  for (const [pattern, Icon] of ICON_BY_KEYWORD) {
    if (pattern.test(tool)) return Icon;
  }
  return Wrench;
}

function elapsedSecondsSince(startedAtIso: string): number {
  return Math.max(0, Math.round((Date.now() - new Date(startedAtIso).getTime()) / 1000));
}

/** Live "(Ns)" counter next to a running tool's label — ticks every second,
 *  cleaned up on unmount (status flips to 'done' and this stops rendering). */
function ToolElapsed({ startedAtIso }: { startedAtIso: string }) {
  const [seconds, setSeconds] = useState(() => elapsedSecondsSince(startedAtIso));

  useEffect(() => {
    const id = window.setInterval(() => setSeconds(elapsedSecondsSince(startedAtIso)), 1000);
    return () => window.clearInterval(id);
  }, [startedAtIso]);

  return (
    <span className="flex-shrink-0 font-mono text-fg-subtle" dir="ltr">
      ({seconds}s)
    </span>
  );
}

function StatusIndicator({ running, failed }: { running: boolean; failed: boolean }) {
  if (running) {
    return (
      <span
        className="h-2 w-2 flex-shrink-0 rounded-full bg-signal animate-cursor-pulse"
        aria-hidden
      />
    );
  }
  if (failed) {
    return (
      <AlertTriangle size={12} strokeWidth={2.5} className="flex-shrink-0 text-danger" aria-hidden />
    );
  }
  return <Check size={12} strokeWidth={2.5} className="flex-shrink-0 text-success" aria-hidden />;
}

/** A tool call that finished unsuccessfully. Shared with ToolCallGroup. */
export function isFailedTool(message: ChatMessage): boolean {
  return message.toolPhase === 'done' && (message.toolOk === false || message.isError);
}

export function ToolCallRow({ message }: { message: ChatMessage }) {
  const running = message.toolPhase !== 'done';
  const failed = isFailedTool(message);
  const Icon = getToolIcon(message.tool);
  const label = message.toolLabel || message.tool || 'Tool';
  const preview = running ? message.text : undefined;
  const result = !running ? message.text : undefined;
  // Every row — failed included — stays collapsed until the reader opens it.
  //
  // Failed rows used to auto-expand, which meant one expected miss (a Read of
  // a file the agent is probing for, a grep with no hits) tore a red block of
  // body text open mid-answer and shoved everything below it down the page.
  // Most mid-turn tool failures are steps the agent recovers from a second
  // later, so the alarm was louder than the news. The failure now reads in the
  // collapsed row itself — danger border, danger icon chip, warning glyph, and
  // the first clamped lines of the error — and opening it stays one click.
  const [userToggled, setUserToggled] = useState(false);
  const expanded = userToggled;
  const expandable = Boolean(result);

  const toggle = () => {
    if (expandable) setUserToggled(!expanded);
  };

  return (
    <div
      role={expandable ? 'button' : 'status'}
      aria-expanded={expandable ? expanded : undefined}
      tabIndex={expandable ? 0 : undefined}
      onClick={toggle}
      onKeyDown={(e) => {
        if (expandable && (e.key === 'Enter' || e.key === ' ')) {
          e.preventDefault();
          toggle();
        }
      }}
      className={`my-0.5 flex items-start gap-2 rounded-md border px-2.5 py-1.5 text-xs transition-colors duration-fast ease-tool ${
        failed
          ? 'border-danger/25 bg-danger-subtle/25'
          : running
            ? 'border-signal/30 bg-signal-subtle/40'
            : 'border-line bg-surface-raised'
      } ${expandable ? 'cursor-pointer hover:border-line-strong' : ''}`}
    >
      <span
        className={`mt-0.5 flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-sm ${
          failed ? 'bg-danger/15 text-danger' : running ? 'bg-signal/15 text-signal' : 'bg-surface-overlay text-fg-muted'
        }`}
        aria-hidden
      >
        <Icon size={12} strokeWidth={2} />
      </span>

      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-center gap-1.5">
          <StatusIndicator running={running} failed={failed} />
          <span className="flex-shrink-0 font-mono font-medium text-fg" dir="ltr">
            {label}
          </span>
          {running && <ToolElapsed startedAtIso={message.createdAt} />}
          {preview && (
            <MixedBidiText text={preview} className="min-w-0 flex-1 truncate text-fg-subtle" />
          )}
          {expandable && (
            <ChevronDown
              size={11}
              strokeWidth={2.5}
              className={`ms-auto flex-shrink-0 text-fg-subtle transition-transform duration-fast ease-tool ${expanded ? 'rotate-180' : ''}`}
              aria-hidden
            />
          )}
        </div>
        {result && (
          // Body copy stays neutral even on a failure — red-on-red is what made
          // a recoverable miss read as a crash. The chrome carries the signal.
          <MixedBidiText
            text={result}
            className={`mt-0.5 block whitespace-pre-wrap break-words text-fg-muted ${
              expanded ? 'max-h-80 overflow-y-auto' : 'line-clamp-3'
            }`}
          />
        )}
      </div>
    </div>
  );
}
