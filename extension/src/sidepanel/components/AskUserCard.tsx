/**
 * AskUserCard — structured multiple-choice UI for AskUserQuestion tool calls.
 */
import { useState } from 'react';
import { HelpCircle, Check } from 'lucide-react';
import type { ChatMessage } from '../store/sessionStore';
import { MixedBidiText } from '../utils/mixedBidiText';

interface AskUserCardProps {
  message: ChatMessage;
  sessionName: string;
  onSubmit: (
    sessionName: string,
    requestId: string,
    answers: Record<string, string | string[]>,
    customText?: string,
  ) => void;
  onSkip: (sessionName: string, requestId: string) => void;
  /** Sticky panel above composer — tighter max height so actions stay on screen. */
  variant?: 'inline' | 'sticky';
}

export function AskUserCard({
  message,
  sessionName,
  onSubmit,
  onSkip,
  variant = 'inline',
}: AskUserCardProps) {
  const questions = message.permQuestions ?? [];
  const [selections, setSelections] = useState<Record<string, string | string[]>>({});
  const [customText, setCustomText] = useState('');
  const resolved = message.permResolved;

  const toggleSingle = (header: string, label: string) => {
    setSelections((prev) => ({ ...prev, [header]: label }));
  };

  const toggleMulti = (header: string, label: string) => {
    setSelections((prev) => {
      const current = prev[header];
      const arr = Array.isArray(current) ? [...current] : current ? [current] : [];
      const idx = arr.indexOf(label);
      if (idx >= 0) arr.splice(idx, 1);
      else arr.push(label);
      return { ...prev, [header]: arr };
    });
  };

  const allAnswered = questions.every((q) => {
    const val = selections[q.header];
    if (q.multiSelect) return Array.isArray(val) && val.length > 0;
    return typeof val === 'string' && val.length > 0;
  });

  if (resolved) {
    return (
      <div className="my-1.5 rounded-md border border-success/30 bg-success-subtle px-3 py-2 text-2xs text-success">
        <Check size={12} strokeWidth={2.5} className="me-1 inline" />
        Answers sent
      </div>
    );
  }

  const maxHeight =
    variant === 'sticky' ? 'max-h-[min(38vh,300px)]' : 'max-h-[min(48vh,380px)]';

  return (
    <div
      className={`flex flex-col rounded-md border border-signal/40 bg-signal-subtle ${maxHeight} ${
        variant === 'inline' ? 'my-1.5' : ''
      }`}
      dir="auto"
    >
      <p className="shrink-0 flex items-center gap-1.5 px-3 pt-2.5 pb-2 text-xs font-semibold text-signal">
        <HelpCircle size={14} strokeWidth={2} className="shrink-0" />
        <MixedBidiText text={message.permTitle ?? 'Claude has questions'} />
      </p>

      <div className="min-h-0 flex-1 overflow-y-auto px-3">
        <div className="flex flex-col gap-3 pb-2">
          {questions.map((q) => (
            <div key={q.header}>
              <MixedBidiText text={q.header} as="p" className="mb-1 text-xs font-medium text-fg" />
              <MixedBidiText
                text={q.question}
                as="p"
                className="mb-1.5 text-2xs text-fg-muted"
              />
              <div className="flex flex-col gap-1">
                {q.options.map((opt) => {
                  const val = selections[q.header];
                  const selected = q.multiSelect
                    ? Array.isArray(val) && val.includes(opt.label)
                    : val === opt.label;
                  return (
                    <button
                      key={opt.label}
                      type="button"
                      dir="auto"
                      onClick={() =>
                        q.multiSelect
                          ? toggleMulti(q.header, opt.label)
                          : toggleSingle(q.header, opt.label)
                      }
                      className={`bidi-plaintext rounded-md border px-2.5 py-1.5 text-start text-xs transition-colors duration-fast ease-tool ${
                        selected
                          ? 'border-signal bg-surface text-fg'
                          : 'border-line bg-surface/60 text-fg-muted hover:bg-surface-overlay'
                      }`}
                    >
                      <MixedBidiText text={opt.label} className="font-medium" />
                      {opt.description && (
                        <MixedBidiText
                          text={opt.description}
                          as="span"
                          className="mt-0.5 block text-2xs text-fg-subtle"
                        />
                      )}
                    </button>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="shrink-0 border-t border-signal/25 bg-signal-subtle px-3 py-2.5">
        <label className="block text-2xs text-fg-muted">
          הערה נוספת (אופציונלי)
          <input
            type="text"
            value={customText}
            onChange={(e) => setCustomText(e.target.value)}
            dir="auto"
            className="bidi-plaintext mt-1 w-full rounded-md border border-line bg-surface px-2 py-1 text-xs text-fg"
            placeholder="הבהרה חופשית…"
          />
        </label>
        <div className="mt-2 flex flex-wrap gap-1.5">
          <button
            type="button"
            disabled={!allAnswered}
            onClick={() =>
              message.actionId &&
              onSubmit(sessionName, message.actionId, selections, customText || undefined)
            }
            className="rounded-md bg-signal px-3 py-1.5 text-xs font-medium text-signal-contrast hover:bg-signal-hover disabled:opacity-40"
          >
            שלח תשובות
          </button>
          <button
            type="button"
            onClick={() => message.actionId && onSkip(sessionName, message.actionId)}
            className="rounded-md border border-line px-3 py-1.5 text-xs text-fg-muted hover:bg-surface-overlay"
          >
            דלג
          </button>
        </div>
      </div>
    </div>
  );
}
