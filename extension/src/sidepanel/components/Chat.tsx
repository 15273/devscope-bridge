/**
 * Chat — per-session message list (Graphite).
 *
 * - Sticky scroll: auto-scroll to bottom unless the user scrolled up.
 * - "New messages" pill when scrolled up and new content arrives.
 * - Grouped time dividers: a single centered timestamp per 5-minute window
 *   instead of a label on every message (cuts timestamp noise).
 * - Skeleton shimmer while history loads; reconnecting banner.
 * - Markdown rendering for assistant messages; amber streaming cursor.
 */
import { memo, useEffect, useMemo, useRef, useState, useCallback } from 'react';
import { AlertCircle, AlertTriangle, ArrowDown, Check, ChevronRight, RotateCw, X } from 'lucide-react';
import { isEmptyAssistantBubble, type ChatMessage } from '../store/sessionStore';
import type { Agent } from '@/shared/frames';
import { AttachedElementsList } from './composer/ElementContextPreview';
import { PermissionCard } from './PermissionCard';
import { MarkdownMessage } from './MarkdownMessage';
import { MedicCard } from './MedicCard';
import { ParallelAskBubble } from './ParallelAskBubble';
import { EnglishCoachCard } from './EnglishCoachCard';
import { SegmentedMessageBody } from './SegmentedMessageBody';
import { SessionStatusChip } from './SessionStatusChip';
import { SlashCommandCard } from './SlashCommandCard';
import { StreamingCursor, StreamingPlaceholder } from './StreamingIndicators';
import { TodoCard } from './TodoCard';
import { ToolCallRow } from './ToolCallRow';
import { ToolCallGroup, groupChatItems } from './ToolCallGroup';
import { TurnFooter } from './TurnFooter';
import { messageTime } from '../utils/relativeTime';
import { findRunningTool } from '../utils/transcriptSync';
import { MessageListenButton } from './MessageListenButton';

const GROUP_WINDOW_MS = 5 * 60 * 1000;

interface ChatProps {
  messages: ChatMessage[];
  isLoadingHistory: boolean;
  agent: Agent;
  sessionName: string;
  statusLabel?: string;
  queuedSteeringCount?: number;
  reconnecting?: boolean;
  /** Bridge HTTP unreachable (poll/transcript failures) — distinct from WS status. */
  bridgeUnreachable?: boolean;
  onRespondPermission: (
    sessionName: string,
    requestId: string,
    optionId: string,
    extras?: { answers?: Record<string, string | string[]>; custom_text?: string },
  ) => void;
  onOpenTerminal?: (session: string) => void;
  /** Resend a message whose delivery failed / was reported dropped (C3/C6). */
  onRetryMessage?: (session: string, messageId: string) => void;
  /** Remove a still-cancellable queued steering message (C6). */
  onCancelSteering?: (session: string, messageId: string) => void;
  stickyPermissionId?: string;
}

export function Chat({
  messages,
  isLoadingHistory,
  sessionName,
  statusLabel,
  queuedSteeringCount = 0,
  reconnecting = false,
  bridgeUnreachable = false,
  onRespondPermission,
  onOpenTerminal,
  onRetryMessage,
  onCancelSteering,
  stickyPermissionId,
}: ChatProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const programmaticScrollRef = useRef(false);
  const [userScrolledUp, setUserScrolledUp] = useState(false);
  const [showNewPill, setShowNewPill] = useState(false);

  const scrollToBottom = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    programmaticScrollRef.current = true;
    el.scrollTop = el.scrollHeight;
    requestAnimationFrame(() => {
      programmaticScrollRef.current = false;
    });
    setUserScrolledUp(false);
    setShowNewPill(false);
  }, []);

  const handleScroll = useCallback(() => {
    if (programmaticScrollRef.current) return;
    const el = scrollRef.current;
    if (!el) return;
    const distFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    setUserScrolledUp(distFromBottom > 80);
  }, []);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;

    // Only pin to bottom when the user is already near the bottom — never yank
    // them down while they are reading scrollback, even during Working/streaming.
    if (!userScrolledUp) {
      programmaticScrollRef.current = true;
      el.scrollTop = el.scrollHeight;
      requestAnimationFrame(() => {
        programmaticScrollRef.current = false;
      });
      setShowNewPill(false);
    } else {
      setShowNewPill(messages.length > 0);
    }
  }, [messages, userScrolledUp]);

  const lastMsg = messages[messages.length - 1];
  useEffect(() => {
    if (lastMsg?.role !== 'permission' || lastMsg.permResolved) return;
    scrollToBottom();
  }, [lastMsg?.id, lastMsg?.role, lastMsg?.permResolved, scrollToBottom]);

  // Recomputed only when the message list itself changes — not on every parent
  // re-render (activity label, steering count, connection ticks), each of which
  // would otherwise mint fresh group wrappers and fresh `item.messages` arrays.
  const grouped = useMemo(() => groupChatItems(messages), [messages]);
  const runningTool = useMemo(() => findRunningTool(messages), [messages]);

  if (isLoadingHistory && messages.length === 0) {
    return <HistorySkeleton />;
  }

  return (
    <div className="relative z-0 flex min-h-0 flex-1 flex-col overflow-hidden">
      {bridgeUnreachable && (
        <div className="flex shrink-0 items-center gap-2 border-b border-line bg-danger-subtle px-3 py-1.5 text-2xs text-danger">
          <AlertTriangle size={13} strokeWidth={2} aria-hidden />
          Bridge not responding — showing the last known state. Retrying…
        </div>
      )}
      {reconnecting && !bridgeUnreachable && (
        <div className="flex shrink-0 items-center justify-center gap-2 border-b border-warning/30 bg-warning-subtle/40 px-3 py-1.5 text-2xs text-warning">
          <span className="h-1.5 w-1.5 rounded-full bg-warning animate-cursor-pulse" aria-hidden />
          Reconnecting to bridge…
        </div>
      )}
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="flex flex-1 flex-col gap-1 overflow-y-auto px-3 py-3"
      >
        {messages.length === 0 ? (
          <EmptyChat />
        ) : (
          grouped.map((item) => {
            if (item.kind === 'tools') {
              const prev = messages[item.startIndex - 1];
              const first = item.messages[0];
              const showDivider =
                !prev ||
                new Date(first.createdAt).getTime() - new Date(prev.createdAt).getTime() >
                  GROUP_WINDOW_MS;
              return (
                <div key={`tools-${item.messages[0].id}`}>
                  {showDivider && <TimeDivider iso={first.createdAt} />}
                  <ToolCallGroup messages={item.messages} />
                </div>
              );
            }
            const msg = item.message;
            const i = item.index;
            const prev = messages[i - 1];
            const showDivider =
              !prev ||
              new Date(msg.createdAt).getTime() - new Date(prev.createdAt).getTime() >
                GROUP_WINDOW_MS;
            return (
              // Key on turnId when present: a turn-tagged assistant bubble's
              // `.id` is renamed from nextId() to `turn-${turnId}` the moment
              // it adopts a turn (sessionStore.ts attachTurnId) — keying on
              // `.id` alone would remount the row at that instant. `turnId`
              // is unique to at most one assistant message (never set on
              // other roles), so no other message can collide with it.
              <div key={msg.turnId ?? msg.id}>
                {showDivider && <TimeDivider iso={msg.createdAt} />}
                <MessageBubble
                  message={msg}
                  sessionName={sessionName}
                  statusLabel={statusLabel}
                  queuedSteeringCount={queuedSteeringCount}
                  runningTool={runningTool}
                  stickyPermissionId={stickyPermissionId}
                  onRespondPermission={onRespondPermission}
                  onOpenTerminal={onOpenTerminal}
                  onRetryMessage={onRetryMessage}
                  onCancelSteering={onCancelSteering}
                />
              </div>
            );
          })
        )}
        <div ref={bottomRef} />
      </div>

      {showNewPill && (
        <button
          onClick={scrollToBottom}
          className="absolute bottom-3 left-1/2 flex -translate-x-1/2 items-center gap-1.5 rounded-full bg-signal px-3 py-1.5 text-xs font-medium text-signal-contrast shadow-tool transition-colors duration-fast ease-tool hover:bg-signal-hover"
        >
          <ArrowDown size={12} strokeWidth={2.5} />
          New messages
        </button>
      )}
    </div>
  );
}

function TimeDivider({ iso }: { iso: string }) {
  const label = messageTime(iso);
  if (!label) return null;
  return (
    <div className="my-2 flex items-center gap-2 px-1 text-2xs text-fg-subtle" aria-hidden>
      <span className="h-px flex-1 bg-line" />
      <span className="font-mono">{label}</span>
      <span className="h-px flex-1 bg-line" />
    </div>
  );
}

function EmptyChat() {
  return (
    <div className="flex flex-1 items-center justify-center px-4 py-8 text-center text-sm text-fg-subtle">
      Send a message to start this session.
    </div>
  );
}

function HistorySkeleton() {
  return (
    <div className="flex flex-1 animate-pulse flex-col gap-3 overflow-hidden px-3 py-3">
      {[85, 60, 90, 50].map((w, i) => (
        <div key={i} className={`flex ${i % 2 === 0 ? 'justify-end' : 'justify-start'}`}>
          <div className="h-8 rounded-md bg-surface-raised" style={{ width: `${w}%` }} />
        </div>
      ))}
    </div>
  );
}

interface BubbleProps {
  message: ChatMessage;
  sessionName: string;
  statusLabel?: string;
  queuedSteeringCount?: number;
  runningTool?: string;
  stickyPermissionId?: string;
  onRespondPermission: (
    sessionName: string,
    requestId: string,
    optionId: string,
    extras?: { answers?: Record<string, string | string[]>; custom_text?: string },
  ) => void;
  onOpenTerminal?: (session: string) => void;
  onRetryMessage?: (session: string, messageId: string) => void;
  onCancelSteering?: (session: string, messageId: string) => void;
}

const MessageBubble = memo(function MessageBubble({
  message,
  sessionName,
  statusLabel,
  queuedSteeringCount = 0,
  runningTool,
  stickyPermissionId,
  onRespondPermission,
  onOpenTerminal,
  onRetryMessage,
  onCancelSteering,
}: BubbleProps) {
  const isUser = message.role === 'user';
  const time = messageTime(message.createdAt);

  if (message.role === 'tool') {
    return <ToolCallRow message={message} />;
  }

  if (message.role === 'medic') {
    return <MedicCard message={message} onOpenTerminal={onOpenTerminal} />;
  }

  if (message.role === 'ask') {
    if (message.askKind === 'english_coach') {
      return <EnglishCoachCard message={message} />;
    }
    return <ParallelAskBubble message={message} />;
  }

  if (message.role === 'status') {
    return <SessionStatusChip message={message} />;
  }

  if (message.role === 'slash_cmd') {
    return <SlashCommandCard message={message} />;
  }

  if (message.role === 'todo') {
    return <TodoCard message={message} />;
  }

  if (message.role === 'permission') {
    if (
      stickyPermissionId &&
      message.actionId === stickyPermissionId &&
      !message.permResolved
    ) {
      return (
        <p className="my-1 px-1 text-2xs text-fg-muted">
          ↳ Awaiting your answer in the panel above the composer
        </p>
      );
    }
    return (
      <PermissionCard
        message={message}
        sessionName={sessionName}
        onRespond={onRespondPermission}
      />
    );
  }

  if (isUser) {
    const attached = message.context?.elements ?? [];
    const hasText = Boolean(message.text.trim());
    const deliveryFailed = message.delivery === 'failed';
    const cancellable = Boolean(message.steering && onCancelSteering);
    return (
      <div className="flex flex-col items-end py-0.5" title={time}>
        <div className="flex max-w-[88%] items-start gap-1">
          {cancellable && (
            <button
              onClick={() => onCancelSteering?.(sessionName, message.id)}
              title="Cancel this queued message"
              aria-label="Cancel queued message"
              className="mt-1.5 flex-shrink-0 rounded-sm p-0.5 text-fg-subtle transition-colors duration-fast ease-tool hover:bg-danger-subtle hover:text-danger"
            >
              <X size={12} strokeWidth={2.5} />
            </button>
          )}
          <div
            className={`min-w-0 rounded-md px-3 py-2 text-sm leading-[1.55] text-fg ${
              deliveryFailed
                ? 'border border-danger/40 bg-danger-subtle/40'
                : message.steering
                  ? 'border border-signal/40 bg-transparent'
                  : 'bg-signal-subtle'
            }`}
          >
            {hasText && (
              <p dir="auto" className="whitespace-pre-wrap break-words">{message.text}</p>
            )}
            {attached.length > 0 && (
              <AttachedElementsList elements={attached} compact />
            )}
            {!hasText && attached.length === 0 && (
              <p dir="auto" className="whitespace-pre-wrap break-words text-fg-muted">{message.text}</p>
            )}
          </div>
        </div>
        {deliveryFailed && (
          <span className="mt-0.5 flex items-center gap-1.5 pr-1 text-2xs text-danger">
            <AlertCircle size={11} strokeWidth={2} aria-hidden />
            Not delivered
            {onRetryMessage && (
              <button
                onClick={() => onRetryMessage(sessionName, message.id)}
                className="flex items-center gap-0.5 rounded-sm border border-danger/40 px-1 py-px font-medium text-danger transition-colors duration-fast ease-tool hover:bg-danger-subtle"
              >
                <RotateCw size={10} strokeWidth={2.25} aria-hidden />
                Retry
              </button>
            )}
          </span>
        )}
        {message.steering && message.steeringDropWarning && !deliveryFailed && (
          <span className="mt-0.5 flex items-center gap-1.5 pr-1 text-2xs text-warning">
            <AlertTriangle size={11} strokeWidth={2} aria-hidden />
            May have been dropped
            {onRetryMessage && (
              <button
                onClick={() => onRetryMessage(sessionName, message.id)}
                className="flex items-center gap-0.5 rounded-sm border border-warning/40 px-1 py-px font-medium text-warning transition-colors duration-fast ease-tool hover:bg-warning-subtle"
              >
                <RotateCw size={10} strokeWidth={2.25} aria-hidden />
                Resend
              </button>
            )}
          </span>
        )}
        {message.steering && !message.steeringDropWarning && !deliveryFailed && (
          <span className="mt-0.5 pr-1 text-2xs text-signal">בתור — יישלח אחרי שהתשובה הנוכחית תסתיים</span>
        )}
      </div>
    );
  }

  if (message.isError) {
    return (
      <div className="flex justify-start py-0.5" title={time}>
        <div className="flex max-w-[90%] items-start gap-2 rounded-md border border-danger/30 bg-danger-subtle px-3 py-2 text-sm leading-[1.55] text-danger">
          <AlertCircle size={14} strokeWidth={2} className="mt-0.5 flex-shrink-0" />
          <p dir="auto">{message.text}</p>
        </div>
      </div>
    );
  }

  // Nothing to say and nothing on the way: render nothing at all, not even the
  // padded box. This bubble is otherwise a ghost — an empty card holding a lone
  // blinking cursor that never resolves.
  if (isEmptyAssistantBubble(message) && !message.isStreaming) {
    return null;
  }

  const hasSegments = Boolean(message.segments && message.segments.length > 0);

  return (
    <div className="flex justify-start py-0.5" title={time}>
      <div className="min-w-[40px] max-w-[92%] rounded-md bg-surface-raised px-3 py-2">
        {hasSegments ? (
          <SegmentedMessageBody
            segments={message.segments!}
            isStreaming={message.isStreaming}
            statusLabel={statusLabel}
            runningTool={runningTool}
            queuedSteeringCount={queuedSteeringCount}
          />
        ) : message.text ? (
          <>
            <MarkdownMessage text={message.text} isStreaming={message.isStreaming} />
            {message.isStreaming && <StreamingCursor />}
          </>
        ) : message.isStreaming ? (
          <StreamingPlaceholder
            statusLabel={statusLabel}
            runningTool={runningTool}
            queuedSteeringCount={queuedSteeringCount}
          />
        ) : null}
        {message.subAgents && message.subAgents.length > 0 && (
          <SubAgentTree rows={message.subAgents} />
        )}
        {!message.isStreaming && message.text.trim() && (
          <div
            className={`mt-1.5 flex items-center gap-2 border-t border-line/60 pt-1 ${
              message.turnMeta ? 'justify-between' : 'justify-end'
            }`}
          >
            {message.turnMeta && <TurnFooter meta={message.turnMeta} />}
            <MessageListenButton messageId={message.id} text={message.text} />
          </div>
        )}
      </div>
    </div>
  );
});

function SubAgentTree({ rows }: { rows: NonNullable<ChatMessage['subAgents']> }) {
  const [open, setOpen] = useState(true);
  const running = rows.filter((r) => r.phase !== 'done').length;
  return (
    <div className="mt-1.5 rounded-sm border border-line">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-1 px-2 py-1 text-2xs font-medium text-fg-muted transition-colors duration-fast ease-tool hover:text-fg"
      >
        <ChevronRight
          size={11}
          strokeWidth={2.5}
          className={`transition-transform duration-fast ease-tool ${open ? 'rotate-90' : ''}`}
        />
        {rows.length} sub-agent{rows.length === 1 ? '' : 's'}
        {running > 0 && <span className="text-signal">· {running} running</span>}
      </button>
      {open && (
        <div className="border-t border-line px-2 py-1">
          {rows.map((r) => (
            <div key={r.agentId} className="flex items-center gap-1.5 py-0.5 text-2xs">
              <SubAgentStatus row={r} />
              <span className="flex-shrink-0 font-mono text-fg-muted">{r.name}</span>
              <span className="min-w-0 flex-1 truncate text-fg-subtle">
                {r.activity || r.description}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function SubAgentStatus({ row }: { row: NonNullable<ChatMessage['subAgents']>[number] }) {
  if (row.phase === 'done') {
    return row.ok === false ? (
      <X size={11} strokeWidth={2.5} className="flex-shrink-0 text-danger" />
    ) : (
      <Check size={11} strokeWidth={2.5} className="flex-shrink-0 text-success" />
    );
  }
  return (
    <svg className="h-3 w-3 flex-shrink-0 animate-spin text-fg-subtle" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" aria-hidden>
      <path d="M21 12a9 9 0 1 1-6.219-8.56" strokeLinecap="round" />
    </svg>
  );
}

