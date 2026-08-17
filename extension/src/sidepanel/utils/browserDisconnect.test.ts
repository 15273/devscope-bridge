import { describe, expect, it } from 'vitest';
import {
  EXTENSION_DISCONNECTED_BANNER,
  isBrowserExtensionDisconnectedError,
} from './browserDisconnect';

describe('isBrowserExtensionDisconnectedError', () => {
  it('detects bridge 503 detail', () => {
    const msg =
      "error: Browser client not connected (session='google_console', connected=['mom']). Reload DevScope";
    expect(isBrowserExtensionDisconnectedError(msg)).toBe(true);
  });

  it('ignores unrelated errors', () => {
    expect(isBrowserExtensionDisconnectedError('error: tab_not_managed')).toBe(false);
  });
});

describe('EXTENSION_DISCONNECTED_BANNER', () => {
  it('is user-facing copy', () => {
    expect(EXTENSION_DISCONNECTED_BANNER).toContain('Extension not connected');
  });
});
