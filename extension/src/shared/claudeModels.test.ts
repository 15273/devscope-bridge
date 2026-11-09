import { describe, expect, it } from 'vitest';
import {
  CLAUDE_ALIAS_RESOLVED,
  CLAUDE_MODEL_PRESETS,
  claudeModelPreset,
  shortenModelId,
} from './claudeModels';

describe('claudeModels presets', () => {
  it('recommends aliases that track the current generation', () => {
    const recommended = CLAUDE_MODEL_PRESETS.filter((m) => m.group === 'recommended');
    const ids = recommended.map((m) => m.id);
    expect(ids).toEqual([null, 'opus', 'sonnet', 'haiku']);
    expect(claudeModelPreset('opus').label).toBe('Opus 5.5');
    expect(claudeModelPreset('sonnet').label).toBe('Sonnet 5.5');
    expect(claudeModelPreset('haiku').label).toBe('Haiku 5.5');
  });

  it('maps resolved full ids to the same generation labels', () => {
    expect(claudeModelPreset(CLAUDE_ALIAS_RESOLVED.opus).label).toBe('Opus 5.5');
    expect(claudeModelPreset(CLAUDE_ALIAS_RESOLVED.sonnet).label).toBe('Sonnet 5.5');
    expect(claudeModelPreset(CLAUDE_ALIAS_RESOLVED.haiku).label).toBe('Haiku 5.5');
  });

  it('keeps unique preset ids', () => {
    const ids = CLAUDE_MODEL_PRESETS.map((m) => m.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it('shortens unknown full ids', () => {
    expect(shortenModelId('claude-opus-9-9')).toBe('Opus 9.9');
  });
});
