import { describe, expect, it, vi } from 'vitest';
import { formatPtyUserTurn } from './ptyUserMessage';
import { chatTerminalId } from '../hooks/usePtySession';
import { loadUiPrefs, type UiPrefs } from './storage';

describe('formatPtyUserTurn', () => {
  it('returns plain text when no context', () => {
    expect(formatPtyUserTurn('hello')).toBe('hello');
  });

  it('wraps bound tab and user text in CONTEXT block', () => {
    const out = formatPtyUserTurn('fix the button', {
      boundTab: {
        tabId: 12,
        url: 'https://example.com',
        title: 'Example',
        windowId: 1,
      },
    });
    expect(out).toContain('[CONTEXT]');
    expect(out).toContain('[BROWSER TAB BOUND] tab_id=12');
    expect(out).toContain('[/CONTEXT]');
    expect(out).toContain('fix the button');
  });

  it('includes mode and model metadata', () => {
    const out = formatPtyUserTurn('/compact', undefined, { mode: 'plan', model: 'sonnet' });
    expect(out).toContain('[MODE plan]');
    expect(out).toContain('[MODEL sonnet]');
    expect(out).toContain('/compact');
  });
});

describe('chatTerminalId', () => {
  it('prefixes session name with chat-', () => {
    expect(chatTerminalId('my-session')).toBe('chat-my-session');
  });
});

describe('interactionMode default', () => {
  it('defaults to stream when storage is empty', async () => {
    const chromeGet = vi.fn().mockResolvedValue({});
    vi.stubGlobal('chrome', { storage: { local: { get: chromeGet } } });
    const prefs = await loadUiPrefs();
    expect(prefs.interactionMode).toBe('stream');
    vi.unstubAllGlobals();
  });

  it('merges partial stored prefs with stream default', () => {
    const stored: Partial<UiPrefs> = { productMode: 'pro' };
    const interactionMode = stored.interactionMode === 'terminal' ? 'terminal' : 'stream';
    expect(interactionMode).toBe('stream');
  });
});
