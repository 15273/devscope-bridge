/**
 * theme.ts — theme resolution for the side panel.
 *
 * Themes: 'light' | 'dark' (near-black) | 'dim' (dark gray, VS Code-like) and
 * 'system' (follows the OS, choosing light or dark). The preference is stored in
 * localStorage so it can be read synchronously at boot (no flash of wrong theme).
 *
 * Applied as classes on <html>: dark → `dark`; dim → `dark dim` (so any `dark:`
 * utilities still apply, while `.dim` overrides the surface/line tokens with
 * grays — see tailwind.css). light → no class.
 */
export type ThemePref = 'system' | 'light' | 'dark' | 'dim';

type Resolved = 'light' | 'dark' | 'dim';

const STORAGE_KEY = 'ds-theme';

export function getThemePref(): ThemePref {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === 'light' || stored === 'dark' || stored === 'dim' || stored === 'system') {
      return stored;
    }
  } catch {
    /* localStorage unavailable — fall through to system default */
  }
  return 'system';
}

export function prefersDark(): boolean {
  return window.matchMedia('(prefers-color-scheme: dark)').matches;
}

function resolve(pref: ThemePref): Resolved {
  if (pref === 'system') return prefersDark() ? 'dark' : 'light';
  return pref;
}

export function applyTheme(pref: ThemePref): void {
  const cl = document.documentElement.classList;
  const r = resolve(pref);
  cl.remove('dark', 'dim');
  if (r === 'dark') {
    cl.add('dark');
  } else if (r === 'dim') {
    cl.add('dark', 'dim');
  }
}

/** Synchronous boot helper — call before rendering React. */
export function applyStoredTheme(): void {
  applyTheme(getThemePref());
}

export function setThemePref(pref: ThemePref): void {
  try {
    localStorage.setItem(STORAGE_KEY, pref);
  } catch {
    /* ignore persistence failure */
  }
  applyTheme(pref);
}
