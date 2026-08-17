/**
 * useTheme — read/update the theme preference and keep <html> in sync.
 *
 * When the preference is `system`, the hook also re-applies on OS theme change.
 */
import { useCallback, useEffect, useState } from 'react';
import { applyTheme, getThemePref, setThemePref, type ThemePref } from '../theme';

export function useTheme(): { pref: ThemePref; setTheme: (next: ThemePref) => void } {
  const [pref, setPref] = useState<ThemePref>(getThemePref);

  useEffect(() => {
    if (pref !== 'system') return;
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const onChange = () => applyTheme('system');
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, [pref]);

  const setTheme = useCallback((next: ThemePref) => {
    setThemePref(next);
    setPref(next);
  }, []);

  return { pref, setTheme };
}
