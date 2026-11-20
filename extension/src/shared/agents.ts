import type { Agent } from './frames';

export const AGENTS: readonly Agent[] = ['claude', 'cursor', 'codex', 'antigravity', 'grok', 'grok_bot'];

export const AGENT_LABELS: Record<Agent, string> = {
  claude: 'Claude',
  cursor: 'Cursor',
  codex: 'Codex',
  antigravity: 'Antigravity',
  grok: 'Grok',
  grok_bot: 'Grok Bot',
};

export const AGENT_DOT_CLASS: Record<Agent, string> = {
  claude: 'bg-claude',
  cursor: 'bg-cursor',
  codex: 'bg-codex',
  antigravity: 'bg-antigravity',
  grok: 'bg-grok',
  grok_bot: 'bg-grok-bot',
};

export function parseAgent(value: unknown, fallback: Agent = 'claude'): Agent {
  if (
    value === 'claude' ||
    value === 'cursor' ||
    value === 'codex' ||
    value === 'antigravity' ||
    value === 'grok' ||
    value === 'grok_bot'
  ) {
    return value;
  }
  return fallback;
}

export function isOneshotAgent(agent: Agent): boolean {
  return agent === 'cursor' || agent === 'codex' || agent === 'antigravity' || agent === 'grok' || agent === 'grok_bot';
}

export function agentFolderLabel(agent: Agent): string {
  return AGENT_LABELS[agent];
}
