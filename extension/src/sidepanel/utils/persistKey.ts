/**
 * persistKey — cheap per-mutation fingerprint used to gate chrome.storage
 * writes in useSessionManager's "persist history on change" effect.
 *
 * Must change whenever anything about the message list that should be
 * persisted changes — including mutable fields on an otherwise-stable
 * message (e.g. the live todo card keeps a fixed id + empty text across
 * every TodoUpdate frame, so its `todos` array has to be folded in
 * separately or updates would silently never persist).
 */
import type { ChatMessage } from '../store/sessionStore';

function todoFingerprint(message: ChatMessage): string {
  if (!message.todos) return '';
  // Fold content length too, not just status — TodoWrite can revise a todo's
  // wording (content) while its status stays the same, and that edit must
  // still change the fingerprint or the persisted history silently goes stale.
  return message.todos.map((t) => `${t.status}:${t.content.length}`).join(',');
}

export function computePersistKey(messages: ChatMessage[]): string {
  return messages.map((m) => m.id + m.text + todoFingerprint(m)).join('');
}
