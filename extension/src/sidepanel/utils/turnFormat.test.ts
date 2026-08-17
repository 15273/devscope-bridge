import { describe, expect, it } from 'vitest';
import {
  formatDuration,
  formatTokenCount,
  formatThinkingDuration,
  shortModelName,
} from './turnFormat';

describe('formatDuration', () => {
  it('formats milliseconds as 1-decimal seconds', () => {
    expect(formatDuration(3200)).toBe('3.2s');
  });

  it('rounds sub-100ms remainders to one decimal', () => {
    expect(formatDuration(450)).toBe('0.5s');
  });
});

describe('formatTokenCount', () => {
  it('abbreviates counts >= 1000 with a k suffix', () => {
    expect(formatTokenCount(1234)).toBe('1.2k');
  });

  it('leaves counts under 1000 as-is', () => {
    expect(formatTokenCount(480)).toBe('480');
  });

  it('abbreviates exactly at the 1000 boundary', () => {
    expect(formatTokenCount(1000)).toBe('1.0k');
  });
});

describe('shortModelName', () => {
  it('strips a leading claude- vendor prefix', () => {
    expect(shortModelName('claude-sonnet-5')).toBe('sonnet-5');
  });

  it('leaves a model without the claude- prefix untouched', () => {
    expect(shortModelName('gpt-4o')).toBe('gpt-4o');
  });

  it('returns null for a missing model so the segment can be hidden', () => {
    expect(shortModelName(undefined)).toBeNull();
    expect(shortModelName(null)).toBeNull();
    expect(shortModelName('')).toBeNull();
  });
});

describe('formatThinkingDuration', () => {
  it('rounds to the nearest second', () => {
    expect(formatThinkingDuration(1000, 2000)).toBe('חשב 1 שניות');
    expect(formatThinkingDuration(1000, 4600)).toBe('חשב 4 שניות');
  });

  it('floors at 1 second even for sub-second gaps', () => {
    expect(formatThinkingDuration(1000, 1200)).toBe('חשב 1 שניות');
    expect(formatThinkingDuration(1000, 1000)).toBe('חשב 1 שניות');
  });
});
