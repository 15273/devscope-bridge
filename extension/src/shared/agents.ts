import type { Agent } from './frames';

export const AGENTS: readonly Agent[] = ['claude', 'cursor', 'codex', 'antigravity'];

export const AGENT_LABELS: Record<Agent, string> = {
  claude: 'Claude',
  cursor: 'Cursor',
  codex: 'Codex',
  antigravity: 'Antigravity',
};

export const AGENT_DOT_CLASS: Record<Agent, string> = {
  claude: 'bg-claude',
  cursor: 'bg-cursor',
  codex: 'bg-codex',
  antigravity: 'bg-antigravity',
};

export function parseAgent(value: unknown, fallback: Agent = 'claude'): Agent {
  if (
    value === 'claude' ||
    value === 'cursor' ||
    value === 'codex' ||
    value === 'antigravity'
  ) {
    return value;
  }
  return fallback;
}

export function isOneshotAgent(agent: Agent): boolean {
  return agent === 'cursor' || agent === 'codex' || agent === 'antigravity';
}

export function agentFolderLabel(agent: Agent): string {
  return AGENT_LABELS[agent];
}
