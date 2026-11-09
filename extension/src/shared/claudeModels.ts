/**
 * Claude CLI model ids and aliases for the DevScope model picker.
 * Mirrors Claude Code `/model` tiers; aliases (opus, sonnet, haiku, …) are the
 * preferred `--model` values so the picker stays current as Anthropic ships
 * new point releases. Labels show the currently resolved generation.
 */
export type ClaudeModelGroup = 'recommended' | 'aliases' | 'previous';

export interface ClaudeModelPreset {
  id: string | null;
  label: string;
  summary: string;
  group: ClaudeModelGroup;
}

/**
 * Resolved ids observed from `claude -p --model <alias> --output-format json`
 * / stream-json `modelUsage` (Nov 2026). Labels only — picker values stay as
 * aliases so they track the CLI's latest.
 */
export const CLAUDE_ALIAS_RESOLVED = {
  opus: 'claude-opus-5-5',
  sonnet: 'claude-sonnet-5-5',
  haiku: 'claude-haiku-5-5',
} as const;

export const CLAUDE_MODEL_PRESETS: ClaudeModelPreset[] = [
  {
    id: null,
    label: 'Default',
    summary: 'Recommended default for your account — same as clearing --model.',
    group: 'recommended',
  },
  {
    id: 'opus',
    label: 'Opus 5.5',
    summary: 'Alias `opus` → currently claude-opus-5-5 · everyday complex tasks.',
    group: 'recommended',
  },
  {
    id: 'sonnet',
    label: 'Sonnet 5.5',
    summary: 'Alias `sonnet` → currently claude-sonnet-5-5 · routine coding.',
    group: 'recommended',
  },
  {
    id: 'haiku',
    label: 'Haiku 5.5',
    summary: 'Alias `haiku` → currently claude-haiku-5-5 · fastest answers.',
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
    id: 'opus[1m]',
    label: 'opus[1m]',
    summary: 'Alias — Opus with explicit 1M token context.',
    group: 'aliases',
  },
  {
    id: 'sonnet[1m]',
    label: 'sonnet[1m]',
    summary: 'Alias — Sonnet with 1M token context.',
    group: 'aliases',
  },
  {
    id: 'opusplan',
    label: 'opusplan',
    summary: 'Alias — Opus in plan mode, Sonnet for execution.',
    group: 'aliases',
  },
  // Full ids so turn_result / imported sessions still resolve a friendly label.
  {
    id: 'claude-opus-5-5',
    label: 'Opus 5.5',
    summary: 'Pinned full id for current Opus (prefer alias `opus`).',
    group: 'previous',
  },
  {
    id: 'claude-sonnet-5-5',
    label: 'Sonnet 5.5',
    summary: 'Pinned full id for current Sonnet (prefer alias `sonnet`).',
    group: 'previous',
  },
  {
    id: 'claude-haiku-5-5',
    label: 'Haiku 5.5',
    summary: 'Pinned full id for current Haiku (prefer alias `haiku`).',
    group: 'previous',
  },
  {
    id: 'claude-opus-4-8',
    label: 'Opus 4.8',
    summary: 'Previous Opus generation.',
    group: 'previous',
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
    id: 'claude-sonnet-4-6',
    label: 'Sonnet 4.6',
    summary: 'Previous Sonnet generation.',
    group: 'previous',
  },
  {
    id: 'claude-sonnet-4-5',
    label: 'Sonnet 4.5',
    summary: 'Previous Sonnet generation.',
    group: 'previous',
  },
  {
    id: 'claude-haiku-4-5',
    label: 'Haiku 4.5',
    summary: 'Previous Haiku generation.',
    group: 'previous',
  },
  {
    id: 'claude-fable-5',
    label: 'Fable 5',
    summary: 'Pinned Fable id when available on your provider.',
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
