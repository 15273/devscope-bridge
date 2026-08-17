/**
 * useSpeechRelay — STT via hidden iframe (allow="microphone") in the side panel.
 */
import { useCallback, useEffect, useMemo, useRef, useState, type RefObject } from 'react';
import type { SpeechToTextStatus } from './useSpeechToText';
import { isMicGranted, openMicGrantPage } from '../utils/speech/micPermission';

const RELAY_URL = chrome.runtime.getURL('speech-relay.html');
const PARENT_ORIGIN = location.origin;

export interface UseSpeechRelayOptions {
  iframeRef: RefObject<HTMLIFrameElement | null>;
  lang: string;
  onTranscript: (text: string) => void;
  onStatusChange?: (status: SpeechToTextStatus) => void;
}

export function useSpeechRelay({
  iframeRef,
  lang,
  onTranscript,
  onStatusChange,
}: UseSpeechRelayOptions) {
  const [status, setStatus] = useState<SpeechToTextStatus>('idle');
  const [lastError, setLastError] = useState('');
  const [relayReady, setRelayReady] = useState(false);
  const [relaySupported, setRelaySupported] = useState(true);
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

  const postToRelay = useCallback((payload: Record<string, unknown>) => {
    const win = iframeRef.current?.contentWindow;
    if (!win) return false;
    win.postMessage(payload, PARENT_ORIGIN);
    return true;
  }, [iframeRef]);

  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      if (event.origin !== PARENT_ORIGIN) return;
      if (event.source !== iframeRef.current?.contentWindow) return;
      const data = event.data as {
        source?: string;
        phase?: string;
        status?: SpeechToTextStatus;
        text?: string;
        error?: string;
        supported?: boolean;
      };
      if (data?.source !== 'devscope-speech-relay') return;

      if (data.phase === 'ready') {
        setRelayReady(true);
        setRelaySupported(data.supported !== false);
        if (data.supported === false) setStatusSafe('unsupported');
        return;
      }
      if (data.phase === 'transcript' && data.text) {
        onTranscriptRef.current(data.text);
        return;
      }
      if (data.phase === 'status' && data.status) {
        setStatusSafe(data.status, data.error ?? '');
        if (data.status === 'denied') {
          void isMicGranted().then((granted) => {
            if (!granted) void openMicGrantPage();
          });
        }
      }
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, [iframeRef, setStatusSafe]);

  const stop = useCallback(() => {
    postToRelay({ type: 'stt_stop' });
    setStatusSafe('idle');
  }, [postToRelay, setStatusSafe]);

  const start = useCallback(
    (overrideLang?: string) => {
      if (!relayReady) {
        setStatusSafe('error', 'relay_not_ready');
        return;
      }
      if (!relaySupported) {
        setStatusSafe('unsupported');
        return;
      }
      const speechLang = overrideLang ?? langRef.current;
      if (!postToRelay({ type: 'stt_start', lang: speechLang })) {
        setStatusSafe('error', 'relay_not_ready');
      }
    },
    [relayReady, relaySupported, postToRelay, setStatusSafe],
  );

  const toggle = useCallback(() => {
    if (status === 'listening') stop();
    else if (status === 'idle' || status === 'error') start();
  }, [status, start, stop]);

  useEffect(() => () => stop(), [stop]);

  const isListening = status === 'listening';
  const isSupported = relaySupported;

  return useMemo(
    () => ({
      isSupported,
      isListening,
      status,
      lastError,
      start,
      stop,
      toggle,
      relayUrl: RELAY_URL,
    }),
    [isSupported, isListening, status, lastError, start, stop, toggle],
  );
}
