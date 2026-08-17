/**
 * TodoCard — live checklist card for role === 'todo' messages.
 *
 * Mirrors the official VSCode extension's TodoWrite rendering: one card per
 * session, replaced in place on every TodoUpdate frame (see sessionStore's
 * TODO_UPDATE reducer case). Compact + collapsible so it doesn't dominate
 * the chat once the plan grows long.
 *
 *  ┌─ border-left accent ────────────────────────────────┐
 *  │  ▸ משימות  3/7 ✓                                     │
 *  │    ✓ done item (strikethrough)                       │
 *  │    ◐ in-progress item (spinner, activeForm, amber)    │
 *  │    ○ pending item (hollow circle)                     │
 *  └─────────────────────────────────────────────────────┘
 */
import { useState } from 'react';
import { Check, ChevronRight, Circle, ListChecks, Loader2 } from 'lucide-react';
import type { ChatMessage } from '../store/sessionStore';
import type { TodoItem } from '@/shared/frames';

interface TodoCardProps {
  message: ChatMessage;
}

function itemLabel(item: TodoItem): string {
  return item.status === 'in_progress' && item.activeForm ? item.activeForm : item.content;
}

function TodoRow({ item }: { item: TodoItem }) {
  const isDone = item.status === 'completed';
  const isRunning = item.status === 'in_progress';

  return (
    <li className="flex items-start gap-2 py-0.5">
      {isDone ? (
        <Check size={13} strokeWidth={2.5} className="mt-0.5 flex-shrink-0 text-success" aria-hidden />
      ) : isRunning ? (
        <Loader2 size={13} strokeWidth={2} className="mt-0.5 flex-shrink-0 animate-spin text-signal" aria-hidden />
      ) : (
        <Circle size={13} strokeWidth={2} className="mt-0.5 flex-shrink-0 text-fg-subtle" aria-hidden />
      )}
      <span
        dir="auto"
        className={`min-w-0 flex-1 text-2xs leading-relaxed ${
          isDone ? 'text-fg-subtle line-through' : isRunning ? 'font-medium text-signal' : 'text-fg-muted'
        }`}
      >
        {itemLabel(item)}
      </span>
    </li>
  );
}

export function TodoCard({ message }: TodoCardProps) {
  const [open, setOpen] = useState(true);
  const todos = message.todos ?? [];
  const doneCount = todos.filter((t) => t.status === 'completed').length;

  if (todos.length === 0) return null;

  return (
    <div className="my-1 rounded-md border border-line border-l-2 border-l-signal bg-surface-raised px-3 py-2.5">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 text-start"
      >
        <ChevronRight
          size={12}
          strokeWidth={2}
          className={`flex-shrink-0 text-fg-muted transition-transform ${open ? 'rotate-90' : ''}`}
          aria-hidden
        />
        <ListChecks size={13} strokeWidth={2} className="flex-shrink-0 text-fg-muted" aria-hidden />
        <span className="text-xs font-semibold text-fg">משימות</span>
        <span className="text-2xs text-fg-subtle">
          {doneCount}/{todos.length} ✓
        </span>
      </button>
      {open && (
        <ul className="mt-1.5 ps-1">
          {todos.map((item, i) => (
            <TodoRow key={`${item.content}-${i}`} item={item} />
          ))}
        </ul>
      )}
    </div>
  );
}
