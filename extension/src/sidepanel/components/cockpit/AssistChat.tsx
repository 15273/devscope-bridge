/**
 * AssistChat — compact WhatsApp assistant panel.
 *
 * Displays a scrollable message list (user + assistant bubbles, RTL Hebrew).
 * Optional `scopedChat` prop scopes queries to a specific chat and shows a
 * dismissible chip. When an assistant answer contains a suggested reply
 * ("הצעה לתשובה: …"), a שלח button renders that opens ConfirmSendDialog.
 * Loading and error states are always visible — never silent.
 */
import { useState, useCallback, useEffect, useRef } from 'react';
import { X, Send, Bot, User } from 'lucide-react';
import type { Agent, AgentMode } from '@/shared/frames';
import type { UseCockpitReturn, AskResult } from './useCockpit';
import { ConfirmSendDialog } from './ConfirmSendDialog';
import { ModePill } from '../composer/ModePill';
import { loadWaAssistPrefs, saveWaAssistPrefs, type WaAssistPrefs } from '../../utils/storage';

// ── Constants ─────────────────────────────────────────────────────────────────

const SUGGESTION_PREFIX = 'הצעה לתשובה: ';

// ── Types ─────────────────────────────────────────────────────────────────────

export interface ScopedChat {
  chatId: string;
  name: string;
}

interface Message {
  id: number;
  role: 'user' | 'assistant';
  text: string;
  result?: AskResult;
}

interface AssistChatProps {
  ask: UseCockpitReturn['ask'];
  send: UseCockpitReturn['send'];
  scopedChat?: ScopedChat | null;
  onClearScope?: () => void;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Extract the suggested reply text from an assistant answer, if present. */
function extractSuggestion(text: string): string | null {
  const lines = text.split('\n');
  for (const line of lines) {
    if (line.startsWith(SUGGESTION_PREFIX)) {
      return line.slice(SUGGESTION_PREFIX.length).trim();
    }
  }
  return null;
}

/** Render answer text, bolding the suggestion line for visual hierarchy. */
function AnswerText({ text }: { text: string }) {
  const lines = text.split('\n');
  return (
    <span className="whitespace-pre-wrap break-words leading-relaxed">
      {lines.map((line, i) => {
        const isSuggestion = line.startsWith(SUGGESTION_PREFIX);
        return (
          <span key={i}>
            {i > 0 && '\n'}
            {isSuggestion ? (
              <span className="font-semibold text-signal">{line}</span>
            ) : (
              line
            )}
          </span>
        );
      })}
    </span>
  );
}

// ── Suggestion send button ────────────────────────────────────────────────────

interface SuggestionSendProps {
  suggestion: string;
  result: AskResult;
  onSend: UseCockpitReturn['send'];
}

function SuggestionSend({ suggestion, result, onSend }: SuggestionSendProps) {
  const [showConfirm, setShowConfirm] = useState(false);

  const handleConfirm = useCallback(async () => {
    await onSend(result.chat_id, suggestion);
    setShowConfirm(false);
  }, [onSend, result.chat_id, suggestion]);

  return (
    <>
      <button
        type="button"
        onClick={() => setShowConfirm(true)}
        className="mt-2 flex h-7 items-center gap-1.5 rounded-md bg-signal px-3 text-xs font-semibold text-signal-contrast transition-colors duration-fast ease-tool hover:bg-signal-hover"
      >
        <Send size={12} />
        שלח
      </button>

      {showConfirm && (
        <ConfirmSendDialog
          chatName={result.chat_name}
          text={suggestion}
          onConfirm={handleConfirm}
          onCancel={() => setShowConfirm(false)}
        />
      )}
    </>
  );
}

// ── Message bubbles ───────────────────────────────────────────────────────────

interface BubbleProps {
  msg: Message;
  onSend: UseCockpitReturn['send'];
}

function Bubble({ msg, onSend }: BubbleProps) {
  const isUser = msg.role === 'user';
  const suggestion = !isUser && msg.result ? extractSuggestion(msg.text) : null;

  if (isUser) {
    return (
      <div className="flex items-start justify-end gap-2">
        <div className="max-w-[85%] rounded-xl rounded-tl-sm bg-signal px-3 py-2 text-xs text-signal-contrast">
          {msg.text}
        </div>
        <div className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-surface-overlay">
          <User size={12} className="text-fg-muted" />
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-start gap-2">
      <div className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-surface-overlay">
        <Bot size={12} className="text-fg-muted" />
      </div>
      <div className="max-w-[90%] rounded-xl rounded-tr-sm border border-line bg-surface px-3 py-2 text-xs text-fg">
        <AnswerText text={msg.text} />
        {suggestion && msg.result?.chat_id && (
          <SuggestionSend suggestion={suggestion} result={msg.result} onSend={onSend} />
        )}
      </div>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

let msgCounter = 0;
function nextId() {
  return ++msgCounter;
}

export function AssistChat({ ask, send, scopedChat, onClearScope }: AssistChatProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [prefs, setPrefs] = useState<WaAssistPrefs>({ agent: 'cursor', model: null, mode: 'act' });
  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    void loadWaAssistPrefs().then(setPrefs);
  }, []);

  const updatePrefs = useCallback((patch: Partial<WaAssistPrefs>) => {
    setPrefs((prev) => {
      const next = { ...prev, ...patch };
      void saveWaAssistPrefs(next);
      return next;
    });
  }, []);

  // Scroll to bottom whenever messages change
  useEffect(() => {
    if (listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [messages]);

  const handleSubmit = useCallback(async () => {
    const question = input.trim();
    if (!question || loading) return;

    const userMsg: Message = { id: nextId(), role: 'user', text: question };
    setMessages((prev) => [...prev, userMsg]);
    setInput('');
    setLoading(true);
    setError(null);

    try {
      const history = messages.slice(-6).map((m) => ({
        role: m.role,
        content: m.text,
      }));
      const result = await ask(question, {
        chatId: scopedChat?.chatId,
        chatName: scopedChat?.name,
        agent: prefs.agent,
        model: prefs.model,
        mode: prefs.mode,
        history,
      });
      if (result) {
        const assistantMsg: Message = {
          id: nextId(),
          role: 'assistant',
          text: result.answer,
          result,
        };
        setMessages((prev) => [...prev, assistantMsg]);
      }
    } catch (e) {
      const errText = e instanceof Error ? e.message : String(e);
      setError(errText);
      // Remove the user bubble on error so they can retry
      setMessages((prev) => prev.filter((m) => m.id !== userMsg.id));
      setInput(question);
    } finally {
      setLoading(false);
    }
  }, [input, loading, ask, scopedChat, prefs, messages]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        void handleSubmit();
      }
    },
    [handleSubmit],
  );

  return (
    <div dir="rtl" className="flex min-h-0 flex-1 flex-col overflow-hidden">
      {/* Scoped chat chip */}
      {scopedChat && (
        <div className="shrink-0 border-b border-line bg-surface-raised px-3 py-2">
          <div className="flex items-center gap-1.5">
            <span className="text-2xs font-medium text-fg-muted">מתייעץ על:</span>
            <span className="flex items-center gap-1 rounded-full border border-signal/40 bg-signal-subtle px-2 py-0.5 text-2xs font-semibold text-signal">
              {scopedChat.name}
              {onClearScope && (
                <button
                  type="button"
                  onClick={onClearScope}
                  className="flex h-3.5 w-3.5 items-center justify-center rounded-full text-signal transition-colors duration-fast ease-tool hover:bg-signal/20"
                  aria-label="הסר סינון"
                >
                  <X size={10} />
                </button>
              )}
            </span>
          </div>
        </div>
      )}

      {/* Message list */}
      <div
        ref={listRef}
        className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-3"
      >
        {messages.length === 0 && !loading && (
          <div className="flex flex-1 flex-col items-center justify-center gap-2 py-10 text-center">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-surface-overlay">
              <Bot size={20} className="text-fg-muted" />
            </div>
            <p className="text-sm font-medium text-fg">עוזר WhatsApp</p>
            <p className="max-w-[200px] text-xs text-fg-muted leading-relaxed">
              שאל על שיחה ספציפית — מה קורה שם ומה כדאי לענות
            </p>
          </div>
        )}

        {messages.map((msg) => (
          <Bubble key={msg.id} msg={msg} onSend={send} />
        ))}

        {loading && (
          <div className="flex items-start gap-2">
            <div className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-surface-overlay">
              <Bot size={12} className="text-fg-muted" />
            </div>
            <div className="flex items-center gap-1.5 rounded-xl rounded-tr-sm border border-line bg-surface px-3 py-2">
              <span className="inline-block h-1.5 w-1.5 animate-bounce rounded-full bg-fg-muted [animation-delay:0ms]" />
              <span className="inline-block h-1.5 w-1.5 animate-bounce rounded-full bg-fg-muted [animation-delay:150ms]" />
              <span className="inline-block h-1.5 w-1.5 animate-bounce rounded-full bg-fg-muted [animation-delay:300ms]" />
            </div>
          </div>
        )}
      </div>

      {/* Error banner */}
      {error && (
        <div className="shrink-0 border-t border-line bg-danger-subtle px-3 py-2">
          <p className="text-2xs text-danger">{error}</p>
        </div>
      )}

      {/* Agent toolbar */}
      <div className="flex shrink-0 flex-wrap items-center gap-1.5 border-b border-line bg-surface-raised px-3 py-1.5">
        <div className="flex items-center gap-0.5 rounded-md border border-line bg-surface p-0.5">
          {(['cursor', 'claude'] as Agent[]).map((a) => (
            <button
              key={a}
              type="button"
              onClick={() => updatePrefs({ agent: a })}
              className={[
                'rounded px-2 py-0.5 text-2xs font-medium transition-colors duration-fast ease-tool',
                prefs.agent === a ? 'bg-signal text-signal-contrast' : 'text-fg-muted hover:text-fg',
              ].join(' ')}
            >
              {a === 'cursor' ? 'Cursor' : 'Claude'}
            </button>
          ))}
        </div>
        <ModePill mode={prefs.mode} onChange={(mode: AgentMode) => updatePrefs({ mode })} />
      </div>

      {/* Input area */}
      <div className="shrink-0 border-t border-line bg-surface-raised p-3">
        <div className="flex items-end gap-2">
          <textarea
            ref={inputRef}
            dir="rtl"
            rows={2}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={loading}
            placeholder="שאל על צ'אט… (למשל: מה קורה עם ניר ומה לענות)"
            className="min-h-0 flex-1 resize-none rounded-md border border-line bg-surface p-2 text-xs leading-relaxed text-fg placeholder:text-fg-subtle focus:border-signal focus:outline-none disabled:opacity-50"
          />
          <button
            type="button"
            disabled={!input.trim() || loading}
            onClick={() => void handleSubmit()}
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-signal text-signal-contrast transition-colors duration-fast ease-tool hover:bg-signal-hover disabled:cursor-not-allowed disabled:opacity-40"
            aria-label="שלח שאלה"
          >
            <Send size={15} />
          </button>
        </div>
      </div>
    </div>
  );
}
