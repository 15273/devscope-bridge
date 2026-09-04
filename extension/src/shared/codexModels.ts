export interface CodexModelPreset {
  id: string | null;
  label: string;
  summary: string;
  group: 'recommended' | 'previous';
}

export const CODEX_MODEL_PRESETS: CodexModelPreset[] = [
  {
    id: null,
    label: 'Default',
    summary: 'Codex CLI default for this login (usually the latest frontier model).',
    group: 'recommended',
  },
  {
    id: 'gpt-5.6-sol',
    label: 'GPT-5.6 Sol',
    summary: 'Frontier Codex model — default on recent CLI builds.',
    group: 'recommended',
  },
  {
    id: 'gpt-5.6-terra',
    label: 'GPT-5.6 Terra',
    summary: 'Balanced Codex tier.',
    group: 'recommended',
  },
  {
    id: 'gpt-5.6-luna',
    label: 'GPT-5.6 Luna',
    summary: 'Faster Codex tier.',
    group: 'recommended',
  },
  {
    id: 'gpt-5.5',
    label: 'GPT-5.5',
    summary: 'Previous frontier generation.',
    group: 'previous',
  },
  {
    id: 'gpt-5.4',
    label: 'GPT-5.4',
    summary: 'Previous generation.',
    group: 'previous',
  },
  {
    id: 'gpt-5.4-mini',
    label: 'GPT-5.4 Mini',
    summary: 'Smaller previous-generation model.',
    group: 'previous',
  },
];

export function codexModelPreset(modelId: string | null | undefined): CodexModelPreset {
  if (!modelId) return CODEX_MODEL_PRESETS[0];
  const hit = CODEX_MODEL_PRESETS.find((m) => m.id === modelId);
  if (hit) return hit;
  return { id: modelId, label: modelId, summary: modelId, group: 'previous' };
}
