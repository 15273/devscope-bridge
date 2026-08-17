/**
 * useBridgeHealth — probes the local bridge so first-run can guide setup.
 *
 * Re-probes on mount, whenever the stored token changes, on a fast interval
 * while not yet connected (so onboarding advances on its own), and on a slow
 * interval even when connected — a bridge that dies mid-session must not stay
 * green forever (chat-reliability C2).
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { pingBridge, type BridgeHealth } from '../bridge';

const RETRY_MS = 4_000;
const CONNECTED_REPROBE_MS = 30_000;
const TOKEN_KEY = 'bridgeToken';

export function useBridgeHealth(): { health: BridgeHealth | 'checking'; recheck: () => void } {
  const [health, setHealth] = useState<BridgeHealth | 'checking'>('checking');
  const lastProbeAtRef = useRef(0);

  const recheck = useCallback(() => {
    setHealth('checking');
    lastProbeAtRef.current = Date.now();
    pingBridge().then(setHealth);
  }, []);

  useEffect(() => {
    let cancelled = false;
    const probe = () => {
      lastProbeAtRef.current = Date.now();
      pingBridge().then((h) => !cancelled && setHealth(h));
    };
    probe();

    const interval = setInterval(() => {
      setHealth((current) => {
        const due =
          current !== 'connected' ||
          Date.now() - lastProbeAtRef.current >= CONNECTED_REPROBE_MS;
        if (due) probe();
        return current;
      });
    }, RETRY_MS);

    const onStorage = (changes: Record<string, chrome.storage.StorageChange>, area: string) => {
      if (area === 'local' && changes[TOKEN_KEY]) probe();
    };
    chrome.storage.onChanged.addListener(onStorage);

    return () => {
      cancelled = true;
      clearInterval(interval);
      chrome.storage.onChanged.removeListener(onStorage);
    };
  }, []);

  return { health, recheck };
}
