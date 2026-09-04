export interface AntigravityModelPreset {
  id: string | null;
  label: string;
  summary: string;
  group: 'recommended' | 'previous';
}

export const ANTIGRAVITY_MODEL_PRESETS: AntigravityModelPreset[] = [
  {
    id: null,
    label: 'Default',
    summary: 'agy /model default for this Google login.',
    group: 'recommended',
  },
  {
    id: 'gemini-3-pro',
    label: 'Gemini 3 Pro',
    summary: 'Highest-capability Gemini in Antigravity CLI.',
    group: 'recommended',
  },
  {
    id: 'gemini-3-flash',
    label: 'Gemini 3 Flash',
    summary: 'Faster Gemini tier.',
    group: 'recommended',
  },
  {
    id: 'claude-sonnet-4-6',
    label: 'Claude Sonnet 4.6',
    summary: 'Anthropic model via Antigravity (when available).',
    group: 'previous',
  },
];

export function antigravityModelPreset(
  modelId: string | null | undefined,
): AntigravityModelPreset {
  if (!modelId) return ANTIGRAVITY_MODEL_PRESETS[0];
  const hit = ANTIGRAVITY_MODEL_PRESETS.find((m) => m.id === modelId);
  if (hit) return hit;
  return { id: modelId, label: modelId, summary: modelId, group: 'previous' };
}
