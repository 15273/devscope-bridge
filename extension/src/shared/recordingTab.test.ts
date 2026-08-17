import { describe, expect, it } from 'vitest';
import { humanizeRecordingError, isRecordableUrl } from './recordingTab';

describe('isRecordableUrl', () => {
  it('accepts normal https pages', () => {
    expect(isRecordableUrl('https://example.com/app')).toBe(true);
  });

  it('rejects chrome internal pages', () => {
    expect(isRecordableUrl('chrome://extensions')).toBe(false);
  });
});

describe('humanizeRecordingError', () => {
  const sample = 'https://example.com/app?view=jobs';

  it('maps devtools errors on normal pages to close-devtools guidance', () => {
    const msg = humanizeRecordingError('Cannot capture tab with DevTools open', sample);
    expect(msg).toContain('DevTools is open');
    expect(msg).not.toContain('Chrome internal pages');
    expect(msg).toContain('example.com');
  });

  it('maps chrome-page errors on normal pages to invoke-extension guidance', () => {
    const msg = humanizeRecordingError('Chrome pages cannot be captured', sample);
    expect(msg).toContain('blocked tab capture');
    expect(msg).not.toContain('Chrome internal pages');
  });

  it('keeps internal-page wording for chrome:// urls', () => {
    const msg = humanizeRecordingError('Chrome pages cannot be captured', 'chrome://newtab');
    expect(msg).toContain('Chrome internal pages');
  });
});
