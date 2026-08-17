/**
 * ToolCallGroup — compact inline pills for consecutive tool rows (Claude-style).
 */
import { useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import type { ChatMessage } from '../store/sessionStore';
import { ToolCallRow, isFailedTool } from './ToolCallRow';

/** Pills shown before the "+N more" button collapses the rest. */
const PILL_LIMIT = 2;

interface ToolCallGroupProps {
  messages: ChatMessage[];
}

function pillLabel(msg: ChatMessage): string {
  const raw = msg.toolLabel || msg.tool || 'Tool';
  const short = raw.replace(/^Browser · /, '');
  return short.length > 24 ? `${short.slice(0, 23)}…` : short;
}

/**
 * The `limit` pills to show, in call order, preferring failed ones — a failure
 * must never be the thing that got hidden behind "+3 more".
 */
function pillsToShow(messages: ChatMessage[], limit: number): ChatMessage[] {
  const chosen = new Set(messages.filter(isFailedTool).slice(0, limit));
  for (const m of messages) {
    if (chosen.size >= limit) break;
    chosen.add(m);
  }
  return messages.filter((m) => chosen.has(m));
}

function ToolPill({ message }: { message: ChatMessage }) {
  const running = message.toolPhase !== 'done';
  const failed = isFailedTool(message);
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 font-mono text-[10px] ${
        failed
          ? 'border-danger/40 bg-danger-subtle/50 text-danger'
          : running
            ? 'border-signal/40 bg-signal-subtle/50 text-signal'
            : 'border-line bg-surface-raised text-fg-muted'
      }`}
      title={message.text || pillLabel(message)}
    >
      {pillLabel(message)}
      {running ? '…' : failed ? '✗' : '✓'}
    </span>
  );
}

export function ToolCallGroup({ messages }: ToolCallGroupProps) {
  const [expanded, setExpanded] = useState(false);
  const anyRunning = messages.some((m) => m.toolPhase !== 'done');

  // A failure inside the group no longer force-expands it. Blowing a compact
  // pill strip open into full rows the instant one tool missed reflowed the
  // whole answer around a step the agent usually recovers from; the failed
  // pill is tinted and marked, and the reader opens the group when they care.
  if (expanded) {
    return (
      <div className="my-1 space-y-0.5">
        <button
          type="button"
          onClick={() => setExpanded(false)}
          className="mb-0.5 flex items-center gap-1 text-[10px] text-fg-subtle hover:text-fg"
        >
          <ChevronDown size={10} />
          {messages.length} tools
        </button>
        {messages.map((m) => (
          <ToolCallRow key={m.id} message={m} />
        ))}
      </div>
    );
  }

  return (
    <div className="my-1 flex flex-wrap items-center gap-1">
      {messages.length > PILL_LIMIT + 1 ? (
        <>
          {pillsToShow(messages, PILL_LIMIT).map((m) => (
            <ToolPill key={m.id} message={m} />
          ))}
          <button
            type="button"
            onClick={() => setExpanded(true)}
            className="inline-flex items-center gap-0.5 rounded-full border border-line px-2 py-0.5 font-mono text-[10px] text-fg-muted hover:border-signal/40"
          >
            <ChevronRight size={10} />
            +{messages.length - PILL_LIMIT} more
          </button>
        </>
      ) : (
        messages.map((m) => <ToolPill key={m.id} message={m} />)
      )}
      {anyRunning && (
        <span className="text-[10px] text-fg-subtle">running</span>
      )}
    </div>
  );
}

/** Group consecutive tool messages for compact rendering. */
export function groupChatItems(messages: ChatMessage[]): Array<
  | { kind: 'message'; message: ChatMessage; index: number }
  | { kind: 'tools'; messages: ChatMessage[]; startIndex: number }
> {
  const out: Array<
    | { kind: 'message'; message: ChatMessage; index: number }
    | { kind: 'tools'; messages: ChatMessage[]; startIndex: number }
  > = [];
  let i = 0;
  while (i < messages.length) {
    if (messages[i].role !== 'tool') {
      out.push({ kind: 'message', message: messages[i], index: i });
      i += 1;
      continue;
    }
    const batch: ChatMessage[] = [];
    const start = i;
    while (i < messages.length && messages[i].role === 'tool') {
      batch.push(messages[i]);
      i += 1;
    }
    out.push({ kind: 'tools', messages: batch, startIndex: start });
  }
  return out;
}
