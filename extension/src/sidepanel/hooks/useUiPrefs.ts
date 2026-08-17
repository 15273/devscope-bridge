import { useEffect, useState } from 'react';
import { loadUiPrefs, type UiPrefs } from '../utils/storage';

const DEFAULTS: UiPrefs = {
  showClickHighlights: true,
  actionSound: false,
  productMode: 'pro',
  interactionMode: 'stream',
  streamDebug: false,
};

/**
 * Live UiPrefs — loads once and follows chrome.storage changes, so a toggle in
 * Settings (e.g. Pro ↔ Simple product mode) applies without reopening the panel.
 */
export function useUiPrefs(): UiPrefs {
  const [prefs, setPrefs] = useState<UiPrefs>(DEFAULTS);

  useEffect(() => {
    loadUiPrefs().then(setPrefs).catch(() => {});
    const onStorage = (
      changes: Record<string, chrome.storage.StorageChange>,
      area: string,
    ) => {
      if (area !== 'local' || !changes.uiPrefs) return;
      loadUiPrefs().then(setPrefs).catch(() => {});
    };
    chrome.storage.onChanged.addListener(onStorage);
    return () => chrome.storage.onChanged.removeListener(onStorage);
  }, []);

  return prefs;
}
