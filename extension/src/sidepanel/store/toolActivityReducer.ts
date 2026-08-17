/**
 * toolActivityReducer — pure upsert logic for CLI tool-call transcript rows.
 *
 * One AgentActivity lifecycle (running → done/error) for a given call_id must
 * render as ONE permanent chat row that updates in place, not two disconnected
 * messages and not an easy-to-miss ephemeral strip. This module owns exactly
 * that upsert so sessionStore.ts's TOOL_CALL case stays a one-line call-site,
 * mirroring how the bridge extracted tool_display.py out of session_reader.py.
 */
import type { AgentActivity } from '@/shared/frames';
import type { ChatMessage } from './sessionTypes';

interface IdHelpers {
  nextId: () => string;
  nowIso: () => string;
}

/**
 * The bridge appends " — done" (MCP tools) or " done" (CLI tools) to the
 * done-state label. The status icon already conveys completion, so the
 * displayed label is stripped back to its running-state form.
 */
function stripDoneSuffix(label: string): string {
  return label.replace(/\s*—\s*done$/i, '').replace(/\s+done$/i, '');
}

function buildRow(activity: AgentActivity, helpers: IdHelpers, phase: 'start' | 'done'): ChatMessage {
  return {
    id: activity.call_id ?? helpers.nextId(),
    role: 'tool',
    text: activity.detail ?? '',
    isStreaming: false,
    isError: activity.status === 'error',
    createdAt: helpers.nowIso(),
    tool: activity.tool ?? undefined,
    toolLabel: stripDoneSuffix(activity.label),
    actionId: activity.call_id ?? undefined,
    toolPhase: phase,
    ...(phase === 'done' ? { toolOk: activity.status !== 'error' } : {}),
  };
}

/** Insert before a trailing streaming assistant bubble so CHUNK still appends to it. */
function insertBeforeStreamingAssistant(msgs: ChatMessage[], row: ChatMessage): ChatMessage[] {
  const next = [...msgs];
  const last = next[next.length - 1];
  if (last?.role === 'assistant' && last.isStreaming) {
    next.splice(next.length - 1, 0, row);
  } else {
    next.push(row);
  }
  return next;
}

/**
 * Upsert a permanent transcript row for one tool call, keyed by call_id.
 * - status === 'running': insert a new row (no-op if already tracked).
 * - status === 'done' | 'error': update the existing row in place; if no
 *   running row was ever seen (e.g. history backfill raced the WS), insert
 *   the done row directly rather than dropping the result.
 *
 * Activities with call_id == null (ambient "Thinking…" etc.) are not tool
 * calls — callers must route those through the existing ACTIVITY path instead.
 */
export function upsertToolCallRow(
  msgs: ChatMessage[],
  activity: AgentActivity,
  helpers: IdHelpers,
): ChatMessage[] {
  if (!activity.call_id) return msgs;

  const idx = msgs.findIndex((m) => m.role === 'tool' && m.actionId === activity.call_id);

  if (activity.status === 'running') {
    if (idx >= 0) return msgs;
    return insertBeforeStreamingAssistant(msgs, buildRow(activity, helpers, 'start'));
  }

  // 'done' | 'error'
  if (idx < 0) {
    return insertBeforeStreamingAssistant(msgs, buildRow(activity, helpers, 'done'));
  }
  const next = [...msgs];
  next[idx] = {
    ...next[idx],
    toolPhase: 'done',
    toolOk: activity.status !== 'error',
    isError: activity.status === 'error',
    toolLabel: stripDoneSuffix(activity.label),
    text: activity.detail ?? next[idx].text,
  };
  return next;
}
