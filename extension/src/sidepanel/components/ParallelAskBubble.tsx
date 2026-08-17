/**
 * ParallelAskBubble — dashed-border bubble for /ask side-queries (role === 'ask').
 *
 * Rendered distinct from normal assistant turns: dashed border, "↗ Ask" label,
 * the question as subtitle, streaming answer body, and a done/failed state.
 * Keyed by question_id so concurrent asks never bleed into each other.
 *
 * ok=false (ask_done with error) → warning accent.
 */
import type { ChatMessage } from '../store/sessionStore';
import { MarkdownMessage } from './MarkdownMessage';

interface ParallelAskBubbleProps {
  message: ChatMessage;
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

export function ParallelAskBubble({ message }: ParallelAskBubbleProps) {
  const failed = message.askDone && message.askOk === false;
  const isCursorCtx = message.askKind === 'cursor_ctx';
  const isCursorTask = message.askKind === 'cursor_task';
  const label = isCursorTask
    ? '↗ Cursor MCP'
    : isCursorCtx
      ? '↗ Cursor context'
      : '↗ Ask';
  const labelAria = isCursorTask
    ? 'Cursor MCP plugin task'
    : isCursorCtx
      ? 'Cursor codebase context scout'
      : 'Parallel ask query';

  const borderClass = failed
    ? 'border-warning/50 border-dashed'
    : 'border-signal/40 border-dashed';

  const labelClass = failed ? 'text-warning' : 'text-signal';

  return (
    <div className={`my-1 rounded-md border bg-surface-raised px-3 py-2.5 ${borderClass}`}>
      {/* Label row */}
      <div className="mb-1 flex items-center gap-1.5">
        <span className={`text-[11px] font-semibold ${labelClass}`} aria-label={labelAria}>
          {label}
        </span>
        {failed && (
          <span className="rounded-sm bg-warning-subtle px-1.5 py-0.5 text-[10px] font-medium text-warning">
            failed
          </span>
        )}
        {message.askDone && !failed && (
          <span className="rounded-sm bg-success-subtle px-1.5 py-0.5 text-[10px] font-medium text-success">
            done
          </span>
        )}
      </div>

      {/* Question subtitle */}
      {message.permTitle && (
        <p className="mb-1.5 text-2xs text-fg-muted italic leading-[1.55]">
          {message.permTitle}
        </p>
      )}

      {/* Streaming answer */}
      {message.text ? (
        <div className="text-sm text-fg">
          <MarkdownMessage text={message.text} />
          {message.isStreaming && <StreamingCursor />}
        </div>
      ) : message.isStreaming ? (
        <StreamingCursor />
      ) : null}
    </div>
  );
}
