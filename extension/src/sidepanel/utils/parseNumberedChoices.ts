/**
 * parseNumberedChoices — detect trailing "1. … 2. …" option lists in assistant text
 * so the composer can offer quick-reply chips when AskUserQuestion was not used.
 */
import type { ChatMessage } from '../store/sessionStore';

export interface NumberedChoice {
  num: number;
  label: string;
  /** Short reply sent on chip click (usually the option number). */
  replyText: string;
}

const NUMBERED_LINE = /^\s*(\d+)[.)]\s+(.+)$/;

/** Extract a trailing block of consecutive numbered lines (e.g. "1. …" / "2. …"). */
export function extractTrailingNumberedChoices(text: string): NumberedChoice[] {
  const lines = text.split('\n');
  const collected: NumberedChoice[] = [];

  for (let i = lines.length - 1; i >= 0; i--) {
    const trimmed = lines[i].trim();
    if (!trimmed) {
      if (collected.length > 0) continue;
      continue;
    }
    const m = NUMBERED_LINE.exec(trimmed);
    if (!m) {
      if (collected.length > 0) break;
      continue;
    }
    const num = Number(m[1]);
    const label = m[2].trim();
    if (!label) break;
    collected.unshift({ num, label, replyText: String(num) });
  }

  if (collected.length < 2 || collected.length > 6) return [];

  const nums = collected.map((c) => c.num);
  if (nums[0] !== 1 && nums[0] !== 2) return [];
  for (let i = 1; i < nums.length; i++) {
    if (nums[i] !== nums[i - 1] + 1) return [];
  }

  return collected;
}

/** Last assistant turn with trailing numbered choices awaiting a user reply. */
export function quickChoicesFromMessages(messages: ChatMessage[]): NumberedChoice[] {
  if (!messages.length) return [];

  let lastAssistantIdx = -1;
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i];
    if (m.role === 'assistant' && !m.isStreaming && m.text.trim()) {
      lastAssistantIdx = i;
      break;
    }
  }
  if (lastAssistantIdx < 0) return [];

  for (let i = lastAssistantIdx + 1; i < messages.length; i++) {
    const m = messages[i];
    if (m.role === 'user') return [];
    if (m.role === 'assistant') return [];
    if (m.role === 'permission' && !m.permResolved) return [];
  }

  return extractTrailingNumberedChoices(messages[lastAssistantIdx].text);
}

/** True when the last assistant turn looks like a yes/no question (not numbered options). */
function isAwaitingYesNoReply(messages: ChatMessage[], lastAssistantIdx: number): boolean {
  for (let i = lastAssistantIdx + 1; i < messages.length; i++) {
    const m = messages[i];
    if (m.role === 'user') return false;
    if (m.role === 'assistant') return false;
    if (m.role === 'permission' && !m.permResolved) return false;
  }

  const text = messages[lastAssistantIdx].text.trim();
  if (!text || extractTrailingNumberedChoices(text).length >= 2) return false;

  const lastLine = text.split('\n').filter((l) => l.trim()).pop()?.trim() ?? '';
  if (!lastLine.endsWith('?')) return false;

  return (
    /רוצה ש/i.test(lastLine) ||
    /האם (?:ל|ש|אני|תרצה)/i.test(lastLine) ||
    /want me to/i.test(lastLine) ||
    /should i/i.test(lastLine) ||
    /would you like/i.test(lastLine)
  );
}

/** כן/לא chips when Claude asks a plain-text yes/no question (no AskUserQuestion card). */
export function quickYesNoFromMessages(messages: ChatMessage[]): NumberedChoice[] {
  if (!messages.length) return [];

  let lastAssistantIdx = -1;
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i];
    if (m.role === 'assistant' && !m.isStreaming && m.text.trim()) {
      lastAssistantIdx = i;
      break;
    }
  }
  if (lastAssistantIdx < 0 || !isAwaitingYesNoReply(messages, lastAssistantIdx)) return [];

  return [
    { num: 1, label: 'כן', replyText: 'כן' },
    { num: 2, label: 'לא', replyText: 'לא' },
  ];
}

/** Numbered options or yes/no chips for the latest unanswered assistant prompt. */
export function quickRepliesFromMessages(messages: ChatMessage[]): NumberedChoice[] {
  const numbered = quickChoicesFromMessages(messages);
  if (numbered.length > 0) return numbered;
  return quickYesNoFromMessages(messages);
}
