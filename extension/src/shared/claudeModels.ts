/**
 * Claude CLI model ids and aliases for the DevScope model picker.
 * Mirrors Claude Code `/model` tiers; aliases (opus, fable, …) are valid --model values.
 */
export type ClaudeModelGroup = 'recommended' | 'aliases' | 'previous';

export interface ClaudeModelPreset {
  id: string | null;
  label: string;
  summary: string;
  group: ClaudeModelGroup;
}

export const CLAUDE_MODEL_PRESETS: ClaudeModelPreset[] = [
  {
    id: null,
    label: 'Default',
    summary: 'Recommended default for your account — same as clearing --model.',
    group: 'recommended',
  },
  {
    id: 'claude-opus-4-8',
    label: 'Opus 4.8',
    summary: 'Best for everyday complex tasks · 1M context window.',
    group: 'recommended',
  },
  {
    id: 'claude-fable-5',
    label: 'Fable 5',
    summary: 'Most capable for hardest, longest-running agent work · uses limits faster.',
    group: 'recommended',
  },
  {
    id: 'claude-sonnet-4-6',
    label: 'Sonnet 4.6',
    summary: 'Efficient for routine coding and daily tasks.',
    group: 'recommended',
  },
  {
    id: 'claude-haiku-4-5',
    label: 'Haiku 4.5',
    summary: 'Fastest for quick answers and lightweight edits.',
    group: 'recommended',
  },
  {
    id: 'best',
    label: 'best',
    summary: 'Alias — Fable 5 when available, otherwise latest Opus.',
    group: 'aliases',
  },
  {
    id: 'fable',
    label: 'fable',
    summary: 'Alias — resolves to Claude Fable 5 on your provider.',
    group: 'aliases',
  },
  {
    id: 'opus',
    label: 'opus',
    summary: 'Alias — latest Opus (4.8 on Anthropic API).',
    group: 'aliases',
  },
  {
    id: 'opus[1m]',
    label: 'opus[1m]',
    summary: 'Alias — Opus with explicit 1M token context.',
    group: 'aliases',
  },
  {
    id: 'sonnet',
    label: 'sonnet',
    summary: 'Alias — latest Sonnet model.',
    group: 'aliases',
  },
  {
    id: 'sonnet[1m]',
    label: 'sonnet[1m]',
    summary: 'Alias — Sonnet with 1M token context.',
    group: 'aliases',
  },
  {
    id: 'haiku',
    label: 'haiku',
    summary: 'Alias — fast Haiku tier.',
    group: 'aliases',
  },
  {
    id: 'opusplan',
    label: 'opusplan',
    summary: 'Alias — Opus in plan mode, Sonnet for execution.',
    group: 'aliases',
  },
  {
    id: 'claude-opus-4-7',
    label: 'Opus 4.7',
    summary: 'Previous Opus generation.',
    group: 'previous',
  },
  {
    id: 'claude-opus-4-6',
    label: 'Opus 4.6',
    summary: 'Older Opus tier.',
    group: 'previous',
  },
  {
    id: 'claude-opus-4-5',
    label: 'Opus 4.5',
    summary: 'Older Opus tier.',
    group: 'previous',
  },
  {
    id: 'claude-sonnet-4-5',
    label: 'Sonnet 4.5',
    summary: 'Previous Sonnet generation.',
    group: 'previous',
  },
];

const GROUP_LABELS: Record<ClaudeModelGroup, string> = {
  recommended: 'Models',
  aliases: 'CLI aliases',
  previous: 'Previous generations',
};

export function claudeModelGroupLabel(group: ClaudeModelGroup): string {
  return GROUP_LABELS[group];
}

export function claudeModelPreset(modelId: string | null | undefined): ClaudeModelPreset {
  if (!modelId) return CLAUDE_MODEL_PRESETS[0];
  const hit = CLAUDE_MODEL_PRESETS.find((m) => m.id === modelId);
  if (hit) return hit;
  return {
    id: modelId,
    label: shortenModelId(modelId),
    summary: modelId,
    group: 'previous',
  };
}

/** Short label for unknown/custom model ids (e.g. from /model in terminal). */
export function shortenModelId(modelId: string): string {
  if (modelId.includes('[')) return modelId;
  const tail = modelId.replace(/^claude-/, '');
  const parts = tail.split('-');
  if (parts.length >= 2) {
    const tier = parts[0];
    const ver = parts.slice(1).join('.');
    const tierLabel = tier.charAt(0).toUpperCase() + tier.slice(1);
    return `${tierLabel} ${ver}`;
  }
  return modelId;
}
