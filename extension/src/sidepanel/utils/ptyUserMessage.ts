/**
 * ptyUserMessage.ts — format composer text + MessageContext for PTY injection.
 *
 * Mirrors devscope_bridge/context_builder.py preamble layout so interactive
 * Claude receives the same browser/attach context as stream-json mode.
 */
import type { AgentMode, MessageContext, PageAttachment } from '@/shared/frames';
import { BRIDGE_HTTP, authHeaders, getToken } from '../bridge';

const PREAMBLE_HARD_CAP = 2500;

export interface PtyTurnOptions {
  mode?: AgentMode;
  model?: string;
  claudeAgent?: string | null;
}

function summariseAttachmentData(_kind: string, data: unknown): string {
  if (data == null) return '';
  if (typeof data === 'string') {
    if (data.startsWith('data:')) return ' data=<base64>';
    return ` data=${data.slice(0, 200)}`;
  }
  try {
    const raw = JSON.stringify(data);
    return ` data=${raw.slice(0, 400)}`;
  } catch {
    return ' data=<unserializable>';
  }
}

function buildContextLines(context: MessageContext): string[] {
  const parts: string[] = [];

  if (context.boundTab) {
    const bt = context.boundTab;
    parts.push(
      `[BROWSER TAB BOUND] tab_id=${bt.tabId} window_id=${bt.windowId} `
        + `title=${JSON.stringify(bt.title.slice(0, 120))} url=${bt.url}`,
    );
    parts.push(
      'DevScope is bound to this tab. Use browser-control MCP tools WITHOUT tab_id '
        + 'to control it. Work in the bound tab in the BACKGROUND.',
    );
  }

  const hasNotes = (context.elements ?? []).some((el) => Boolean(el.note));

  for (const el of context.elements ?? []) {
    const label = el.note ? '[EDIT TARGET]' : '[ELEMENT]';
    let chunk = label;
    if (el.note) chunk += ` change=${JSON.stringify(el.note.slice(0, 200))}`;
    if (el.editRef) chunk += ` anchor=[data-edit-ref="${el.editRef}"]`;
    chunk += ` selector=${el.selector} tag=${el.tag}`;
    if (el.ariaRole) chunk += ` role=${JSON.stringify(el.ariaRole)}`;
    if (el.ariaName) chunk += ` ariaName=${JSON.stringify(el.ariaName.slice(0, 120))}`;
    if (el.domChain?.length) chunk += ` domChain=${el.domChain.join(' > ')}`;
    if (el.text) chunk += ` text=${JSON.stringify(el.text.slice(0, 120))}`;
    if (el.outerHTML) chunk += ` outerHTML=${JSON.stringify(el.outerHTML.slice(0, 300))}`;
    if (el.cssSnapshot) chunk += ` css=${JSON.stringify(el.cssSnapshot)}`;
    if (el.boundingBox) chunk += ` bbox=${JSON.stringify(el.boundingBox)}`;
    if (el.frameUrl) chunk += ` frame=${el.frameUrl}`;
    if (el.screenshotSnippet) chunk += ' screenshotSnippet=attached';
    parts.push(chunk);
  }

  for (const att of context.attachments ?? []) {
    if (att.kind === 'image') {
      const pathNote = typeof att.data === 'string' && !att.data.startsWith('data:')
        ? ` path=${att.data}`
        : '';
      parts.push(`[IMAGE attached: ${JSON.stringify(att.label)}${pathNote}]`);
      continue;
    }
    let chunk = `[ATTACHMENT kind=${att.kind} label=${JSON.stringify(att.label)}`;
    if (att.url) chunk += ` url=${att.url}`;
    if (att.data != null) chunk += summariseAttachmentData(att.kind, att.data);
    chunk += ']';
    parts.push(chunk);
  }

  if (hasNotes) {
    parts.unshift(
      'The user annotated specific page elements with changes they want. '
        + 'Each [EDIT TARGET] has a `change=` instruction.',
    );
  }

  return parts;
}

function buildMetaLines(opts?: PtyTurnOptions): string[] {
  const lines: string[] = [];
  if (opts?.mode) lines.push(`[MODE ${opts.mode}]`);
  if (opts?.model) lines.push(`[MODEL ${opts.model}]`);
  if (opts?.claudeAgent) lines.push(`[AGENT ${opts.claudeAgent}]`);
  return lines;
}

/** Format a user turn for injection into the interactive Claude PTY. */
export function formatPtyUserTurn(
  text: string,
  context?: MessageContext,
  opts?: PtyTurnOptions,
): string {
  const trimmed = text.trim();
  const meta = buildMetaLines(opts);
  const ctxLines = context ? buildContextLines(context) : [];

  if (meta.length === 0 && ctxLines.length === 0) {
    return trimmed;
  }

  const blocks: string[] = ['[CONTEXT]'];
  blocks.push(...meta, ...ctxLines);
  blocks.push('[/CONTEXT]', '', trimmed);
  let out = blocks.join('\n');
  if (out.length > PREAMBLE_HARD_CAP) {
    out = `${out.slice(0, PREAMBLE_HARD_CAP)}\n[context truncated]\n\n${trimmed}`;
  }
  return out;
}

function attachmentFilename(att: PageAttachment, index: number): string {
  const base = att.label.replace(/[^a-zA-Z0-9._-]+/g, '-').slice(0, 40) || `attach-${index}`;
  if (att.kind === 'image' || att.kind === 'screenshot') return `${base}.png`;
  if (att.kind === 'snapshot') return `${base}.txt`;
  return `${base}.json`;
}

/** Persist image data URLs to bridge outbox; returns context with file paths. */
export async function persistOutboxAttachments(
  sessionName: string,
  context?: MessageContext,
): Promise<MessageContext | undefined> {
  if (!context?.attachments?.length) return context;

  const token = await getToken().catch(() => '');
  if (!token) return context;

  const attachments = await Promise.all(
    context.attachments.map(async (att, index) => {
      if (att.kind !== 'image' || typeof att.data !== 'string' || !att.data.startsWith('data:')) {
        return att;
      }
      const filename = attachmentFilename(att, index);
      try {
        const res = await fetch(
          `${BRIDGE_HTTP}/fs/outbox/${encodeURIComponent(sessionName)}`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
            body: JSON.stringify({ filename, data_url: att.data }),
          },
        );
        if (!res.ok) return att;
        const body = await res.json() as { ok?: boolean; path?: string };
        if (!body.ok || !body.path) return att;
        return { ...att, data: body.path };
      } catch {
        return att;
      }
    }),
  );

  return { ...context, attachments };
}
