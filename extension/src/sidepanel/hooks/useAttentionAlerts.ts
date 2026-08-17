/**
 * useAttentionAlerts — fire sound / title flash / notifications when a session needs input.
 */
import { useEffect, useMemo, useRef } from 'react';
import type { SessionState } from '../store/sessionStore';
import type { AttentionPrefs } from '../utils/storage';
import { buildAttentionMap, type SessionAttention } from '../utils/sessionAttention';
import {
  playAttentionChime,
  showAttentionNotification,
  startTitleFlash,
} from '../utils/attentionAlerts';

function shouldFireSideEffects(
  sessionName: string,
  activeSession: string | null,
  panelVisible: boolean,
  alertWhenActive: boolean,
): boolean {
  if (!panelVisible) return true;
  if (sessionName !== activeSession) return true;
  return alertWhenActive;
}

export function useAttentionAlerts(
  sessions: SessionState[],
  activeSession: string | null,
  prefs: AttentionPrefs,
): Map<string, SessionAttention> {
  const attentionMap = useMemo(() => buildAttentionMap(sessions), [sessions]);
  const alertedRef = useRef<Set<string>>(new Set());
  const stopFlashRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    if (!prefs.enabled) {
      stopFlashRef.current?.();
      stopFlashRef.current = null;
      alertedRef.current.clear();
      return;
    }

    const panelVisible = document.visibilityState === 'visible';
    const activeSignatures = new Set(
      [...attentionMap.values()].map((a) => `${a.sessionName}:${a.signature}`),
    );

    for (const sig of [...alertedRef.current]) {
      if (!activeSignatures.has(sig)) alertedRef.current.delete(sig);
    }

    for (const att of attentionMap.values()) {
      const dedupeKey = `${att.sessionName}:${att.signature}`;
      if (alertedRef.current.has(dedupeKey)) continue;

      if (
        !shouldFireSideEffects(
          att.sessionName,
          activeSession,
          panelVisible,
          prefs.alertWhenActive,
        )
      ) {
        continue;
      }

      alertedRef.current.add(dedupeKey);

      if (prefs.sound) playAttentionChime();

      if (prefs.flashTitle && !panelVisible) {
        stopFlashRef.current?.();
        stopFlashRef.current = startTitleFlash('●');
      }

      if (prefs.desktopNotification) {
        void showAttentionNotification(att.sessionName, att.label);
      }
    }

    if (attentionMap.size === 0 || panelVisible) {
      stopFlashRef.current?.();
      stopFlashRef.current = null;
    }
  }, [attentionMap, activeSession, prefs]);

  useEffect(() => {
    const onVis = () => {
      if (document.visibilityState === 'visible') {
        stopFlashRef.current?.();
        stopFlashRef.current = null;
      }
    };
    document.addEventListener('visibilitychange', onVis);
    return () => {
      document.removeEventListener('visibilitychange', onVis);
      stopFlashRef.current?.();
    };
  }, []);

  return attentionMap;
}
