export interface GrokModelPreset {
  id: string | null;
  label: string;
  summary: string;
  group: 'recommended' | 'previous';
}

export const GROK_MODEL_PRESETS: GrokModelPreset[] = [
  {
    id: null,
    label: 'Default',
    summary: 'Grok CLI default for this login (currently grok-4.6).',
    group: 'recommended',
  },
  {
    id: 'grok-4.6',
    label: 'Grok 4.6',
    summary: 'Current Grok coding model.',
    group: 'recommended',
  },
  {
    id: 'grok-4.5',
    label: 'Grok 4.5',
    summary: 'Previous Grok generation.',
    group: 'previous',
  },
];

export function grokModelPreset(modelId: string | null | undefined): GrokModelPreset {
  if (!modelId) return GROK_MODEL_PRESETS[0];
  return GROK_MODEL_PRESETS.find((p) => p.id === modelId) ?? {
    id: modelId,
    label: modelId,
    summary: 'Custom Grok model id.',
    group: 'previous',
  };
}
