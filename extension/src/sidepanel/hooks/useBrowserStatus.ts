/**
 * useBrowserStatus — profile label + whether this Chrome profile can list tabs.
 */
import { useCallback, useEffect, useState } from 'react';
import type { ProfileIdentityResponse } from '@/shared/messaging';
import { listTabsViaBackground } from '../utils/autoBindTab';

export interface BrowserStatus {
  profileLabel: string | null;
  browserReachable: boolean | null;
  tabCount: number;
  recheck: () => void;
}

export function useBrowserStatus(enabled: boolean): BrowserStatus {
  const [profileLabel, setProfileLabel] = useState<string | null>(null);
  const [browserReachable, setBrowserReachable] = useState<boolean | null>(null);
  const [tabCount, setTabCount] = useState(0);

  const recheck = useCallback(() => {
    if (!enabled) return;
    chrome.runtime
      .sendMessage({ kind: 'get_profile_identity' })
      .then((res: ProfileIdentityResponse) => {
        if (res?.ok && res.profileLabel) setProfileLabel(res.profileLabel);
      })
      .catch(() => {});
    listTabsViaBackground()
      .then((tabs) => {
        setBrowserReachable(true);
        setTabCount(tabs.length);
      })
      .catch(() => {
        setBrowserReachable(false);
        setTabCount(0);
      });
  }, [enabled]);

  useEffect(() => {
    if (!enabled) return;
    recheck();
    const id = setInterval(recheck, 20_000);
    return () => clearInterval(id);
  }, [enabled, recheck]);

  return { profileLabel, browserReachable, tabCount, recheck };
}
