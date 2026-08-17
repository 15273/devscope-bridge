/**
 * Browser speech-to-text — appends transcribed text into the composer.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  getSpeechRecognitionCtor,
  type SpeechRecognitionErrorEvent,
  type SpeechRecognitionInstance,
  type SpeechRecognitionResultEvent,
} from '@/shared/speech/speechRecognition';

export type SpeechToTextStatus = 'idle' | 'listening' | 'unsupported' | 'denied' | 'error';

export interface UseSpeechToTextOptions {
  lang: string;
  onTranscript: (text: string) => void;
  onStatusChange?: (status: SpeechToTextStatus) => void;
}

export function useSpeechToText({ lang, onTranscript, onStatusChange }: UseSpeechToTextOptions) {
  const [status, setStatus] = useState<SpeechToTextStatus>('idle');
  const [lastError, setLastError] = useState('');
  const recognitionRef = useRef<SpeechRecognitionInstance | null>(null);
  const listeningRef = useRef(false);
  const generationRef = useRef(0);
  const onTranscriptRef = useRef(onTranscript);
  const onStatusChangeRef = useRef(onStatusChange);

  useEffect(() => {
    onTranscriptRef.current = onTranscript;
    onStatusChangeRef.current = onStatusChange;
  }, [onTranscript, onStatusChange]);

  const setStatusSafe = useCallback((next: SpeechToTextStatus) => {
    setStatus(next);
    onStatusChangeRef.current?.(next);
  }, []);

  useEffect(() => {
    if (!getSpeechRecognitionCtor()) {
      setStatusSafe('unsupported');
    }
  }, [setStatusSafe]);

  const stop = useCallback(() => {
    generationRef.current += 1;
    listeningRef.current = false;
    const rec = recognitionRef.current;
    recognitionRef.current = null;
    try {
      rec?.stop();
    } catch {
      /* already stopped */
    }
    setStatusSafe('idle');
  }, [setStatusSafe]);

  const start = useCallback(
    (overrideLang?: string) => {
      const Ctor = getSpeechRecognitionCtor();
      if (!Ctor) {
        setStatusSafe('unsupported');
        return;
      }

      generationRef.current += 1;
      const gen = generationRef.current;
      listeningRef.current = false;
      const prev = recognitionRef.current;
      recognitionRef.current = null;
      try {
        prev?.abort();
      } catch {
        try {
          prev?.stop();
        } catch {
          /* ignore */
        }
      }

      const recognition = new Ctor();
      recognition.continuous = true;
      recognition.interimResults = true;
      recognition.lang = overrideLang ?? lang;
      recognition.maxAlternatives = 1;

      recognition.onresult = (event: SpeechRecognitionResultEvent) => {
        if (gen !== generationRef.current) return;
        let transcript = '';
        for (let i = 0; i < event.results.length; i++) {
          transcript += event.results[i][0]?.transcript ?? '';
        }
        const trimmed = transcript.trim();
        if (trimmed) onTranscriptRef.current(trimmed);
      };

      recognition.onerror = (event: SpeechRecognitionErrorEvent) => {
        if (gen !== generationRef.current) return;
        const code = event.error ?? 'unknown';
        setLastError(code);

        if (code === 'not-allowed' || code === 'service-not-allowed') {
          setStatusSafe('denied');
          listeningRef.current = false;
          recognitionRef.current = null;
          return;
        }
        if (code === 'aborted' || code === 'no-speech') return;

        setStatusSafe('error');
        listeningRef.current = false;
        recognitionRef.current = null;
      };

      recognition.onend = () => {
        if (gen !== generationRef.current) return;
        if (listeningRef.current && recognitionRef.current === recognition) {
          try {
            recognition.start();
          } catch {
            listeningRef.current = false;
            recognitionRef.current = null;
            setStatusSafe('idle');
          }
          return;
        }
        setStatusSafe('idle');
      };

      try {
        recognition.start();
        recognitionRef.current = recognition;
        listeningRef.current = true;
        setLastError('');
        setStatusSafe('listening');
      } catch (err) {
        setLastError(err instanceof Error ? err.message : 'start_failed');
        setStatusSafe('error');
        listeningRef.current = false;
        recognitionRef.current = null;
      }
    },
    [lang, setStatusSafe],
  );

  const toggle = useCallback(() => {
    if (status === 'listening') stop();
    else if (status === 'idle' || status === 'error') start();
  }, [status, start, stop]);

  useEffect(() => () => stop(), [stop]);

  const isSupported = status !== 'unsupported' && getSpeechRecognitionCtor() !== null;
  const isListening = status === 'listening';

  return useMemo(
    () => ({
      isSupported,
      isListening,
      status,
      lastError,
      start,
      stop,
      toggle,
    }),
    [isSupported, isListening, status, lastError, start, stop, toggle],
  );
}
