/**
 * commands.ts — composer command + attach-action definitions.
 *
 * Native commands trigger in-app behavior (mode switch, attach, pick, help).
 * Custom commands (from the bridge's /commands) are inserted as text for the agent.
 */
import { Activity, Camera, Layers, Terminal } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import type { AgentMode, PageAttachment, PageAttachmentKind } from '@/shared/frames';
import type { SlashCommand } from '../../bridge';

export type NativeAction = 'mode' | 'attach' | 'pick' | 'help' | 'clear' | 'reset' | 'export';

export interface NativeCommand extends SlashCommand {
  source: 'native';
  action: NativeAction;
  arg?: string;
}

export const NATIVE_COMMANDS: NativeCommand[] = [
  { name: '/act', description: 'Switch to Act mode', source: 'native', action: 'mode', arg: 'act' },
  { name: '/plan', description: 'Switch to Plan mode', source: 'native', action: 'mode', arg: 'plan' },
  { name: '/inspect', description: 'Switch to Inspect mode', source: 'native', action: 'mode', arg: 'inspect' },
  { name: '/test', description: 'Switch to Test mode', source: 'native', action: 'mode', arg: 'test' },
  { name: '/pick', description: 'Pick an element on the page', source: 'native', action: 'pick' },
  { name: '/screenshot', description: 'Attach a screenshot of the page', source: 'native', action: 'attach', arg: 'screenshot' },
  { name: '/snapshot', description: 'Attach the page structure', source: 'native', action: 'attach', arg: 'snapshot' },
  { name: '/console', description: 'Attach console output', source: 'native', action: 'attach', arg: 'console' },
  { name: '/network', description: 'Attach network activity', source: 'native', action: 'attach', arg: 'network' },
  { name: '/help', description: 'Open the glossary', source: 'native', action: 'help' },
  { name: '/clear', description: 'Clear attached context', source: 'native', action: 'clear' },
  { name: '/reset', description: 'Recover a stuck session (fresh process, keeps history)', source: 'native', action: 'reset' },
  { name: '/export', description: 'Export the current chat to a Markdown file and download it', source: 'native', action: 'export' },
];

export function isNativeCommand(cmd: SlashCommand): cmd is NativeCommand {
  return cmd.source === 'native';
}

/**
 * True for commands that are interactive-terminal-only and must not be sent.
 * Selecting a disabled command in the menu shows the note and does nothing.
 */
export function isDisabledCommand(cmd: SlashCommand): boolean {
  return cmd.disabled === true;
}

/** Toolbar attach actions: capture a slice of page state → context chip. */
export interface AttachAction {
  kind: PageAttachmentKind;
  tool: string;
  label: string;
  icon: LucideIcon;
}

export const ATTACH_ACTIONS: AttachAction[] = [
  { kind: 'screenshot', tool: 'browser_screenshot', label: 'Screenshot', icon: Camera },
  { kind: 'snapshot', tool: 'browser_snapshot', label: 'Snapshot', icon: Layers },
  { kind: 'console', tool: 'browser_get_console', label: 'Console', icon: Terminal },
  { kind: 'network', tool: 'browser_get_network', label: 'Network', icon: Activity },
];

const KIND_LABEL: Record<PageAttachmentKind, string> = {
  screenshot: 'Screenshot',
  snapshot: 'Snapshot',
  console: 'Console',
  network: 'Network',
  page_info: 'Page info',
  image: 'Image',
};

export function toAttachment(kind: PageAttachmentKind, data: unknown): PageAttachment {
  const url = (data as { url?: string })?.url;
  let host = '';
  if (url) {
    try {
      host = new URL(url).host;
    } catch {
      host = '';
    }
  }
  return {
    kind,
    label: host ? `${KIND_LABEL[kind]} · ${host}` : KIND_LABEL[kind],
    url,
    data,
  };
}

export const MODE_IDS: AgentMode[] = ['act', 'plan', 'inspect', 'test'];
