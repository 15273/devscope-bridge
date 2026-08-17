/**
 * useOffscreenSpeechToText — STT via the offscreen document (side panel cannot prompt for mic).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { SpeechToTextStatus } from './useSpeechToText';
import { isMicGranted, openMicGrantPage } from '../utils/speech/micPermission';

export interface UseOffscreenSpeechToTextOptions {
  lang: string;
  onTranscript: (text: string) => void;
  onStatusChange?: (status: SpeechToTextStatus) => void;
}

async function wakeOffscreen(): Promise<void> {
  const resp = (await chrome.runtime.sendMessage({ kind: 'wake_offscreen' })) as {
    ok?: boolean;
  };
  if (!resp?.ok) throw new Error('offscreen_unavailable');
}

export function useOffscreenSpeechToText({
  lang,
  onTranscript,
  onStatusChange,
}: UseOffscreenSpeechToTextOptions) {
  const [status, setStatus] = useState<SpeechToTextStatus>('idle');
  const [lastError, setLastError] = useState('');
  const onTranscriptRef = useRef(onTranscript);
  const onStatusChangeRef = useRef(onStatusChange);
  const langRef = useRef(lang);

  useEffect(() => {
    onTranscriptRef.current = onTranscript;
    onStatusChangeRef.current = onStatusChange;
    langRef.current = lang;
  }, [onTranscript, onStatusChange, lang]);

  const setStatusSafe = useCallback((next: SpeechToTextStatus, error = '') => {
    setStatus(next);
    if (error) setLastError(error);
    onStatusChangeRef.current?.(next);
  }, []);

  useEffect(() => {
    const onMessage = (msg: {
      kind?: string;
      phase?: string;
      status?: SpeechToTextStatus;
      text?: string;
      error?: string;
    }) => {
      if (msg?.kind !== 'speech_stt_event') return;
      if (msg.phase === 'transcript' && msg.text) {
        onTranscriptRef.current(msg.text);
        return;
      }
      if (msg.phase === 'status' && msg.status) {
        setStatusSafe(msg.status, msg.error ?? '');
        if (msg.status === 'denied') {
          void isMicGranted().then((granted) => {
            if (!granted) void openMicGrantPage();
          });
        }
      }
    };
    chrome.runtime.onMessage.addListener(onMessage);
    return () => chrome.runtime.onMessage.removeListener(onMessage);
  }, [setStatusSafe]);

  const stop = useCallback(() => {
    chrome.runtime.sendMessage({ kind: 'speech_stt_stop' }).catch(() => {});
    setStatusSafe('idle');
  }, [setStatusSafe]);

  const start = useCallback(
    (overrideLang?: string) => {
      const speechLang = overrideLang ?? langRef.current;
      void wakeOffscreen()
        .then(() =>
          chrome.runtime.sendMessage({ kind: 'speech_stt_start', lang: speechLang }),
        )
        .catch(() => setStatusSafe('error', 'offscreen_unavailable'));
    },
    [setStatusSafe],
  );

  const toggle = useCallback(() => {
    if (status === 'listening') stop();
    else if (status === 'idle' || status === 'error') start();
  }, [status, start, stop]);

  useEffect(() => () => stop(), [stop]);

  const isListening = status === 'listening';

  return useMemo(
    () => ({
      isSupported: true,
      isListening,
      status,
      lastError,
      start,
      stop,
      toggle,
    }),
    [isListening, status, lastError, start, stop, toggle],
  );
}
