/**
 * speechRecognitionHost — Web Speech API STT inside the offscreen document.
 *
 * Chrome side panels suppress mic permission prompts; offscreen (USER_MEDIA) can
 * capture audio once the extension has site mic access.
 */
import {
  getSpeechRecognitionCtor,
  type SpeechRecognitionErrorEvent,
  type SpeechRecognitionInstance,
  type SpeechRecognitionResultEvent,
} from '@/shared/speech/speechRecognition';

export type SttHostStatus = 'idle' | 'listening' | 'unsupported' | 'denied' | 'error';

let recognitionRef: SpeechRecognitionInstance | null = null;
let listening = false;
let generation = 0;

function broadcast(event: Record<string, unknown>): void {
  chrome.runtime
    .sendMessage({ kind: 'speech_stt_event', ...event })
    .catch(() => {});
}

export function probeSpeechRecognition(): boolean {
  return getSpeechRecognitionCtor() !== null;
}

export function stopSpeechRecognition(): void {
  generation += 1;
  listening = false;
  const rec = recognitionRef;
  recognitionRef = null;
  try {
    rec?.abort();
  } catch {
    try {
      rec?.stop();
    } catch {
      /* ignore */
    }
  }
  broadcast({ phase: 'status', status: 'idle' });
}

export function startSpeechRecognition(lang: string): void {
  const Ctor = getSpeechRecognitionCtor();
  if (!Ctor) {
    broadcast({ phase: 'status', status: 'unsupported' });
    return;
  }

  generation += 1;
  const gen = generation;
  listening = false;
  const prev = recognitionRef;
  recognitionRef = null;
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
  recognition.lang = lang;
  recognition.maxAlternatives = 1;

  recognition.onresult = (event: SpeechRecognitionResultEvent) => {
    if (gen !== generation) return;
    let transcript = '';
    for (let i = 0; i < event.results.length; i++) {
      transcript += event.results[i][0]?.transcript ?? '';
    }
    const trimmed = transcript.trim();
    if (trimmed) broadcast({ phase: 'transcript', text: trimmed });
  };

  recognition.onerror = (event: SpeechRecognitionErrorEvent) => {
    if (gen !== generation) return;
    const code = event.error ?? 'unknown';
    if (code === 'not-allowed' || code === 'service-not-allowed') {
      listening = false;
      recognitionRef = null;
      broadcast({ phase: 'status', status: 'denied', error: code });
      return;
    }
    if (code === 'aborted' || code === 'no-speech') return;
    listening = false;
    recognitionRef = null;
    broadcast({ phase: 'status', status: 'error', error: code });
  };

  recognition.onend = () => {
    if (gen !== generation) return;
    if (listening && recognitionRef === recognition) {
      try {
        recognition.start();
      } catch {
        listening = false;
        recognitionRef = null;
        broadcast({ phase: 'status', status: 'idle' });
      }
      return;
    }
    broadcast({ phase: 'status', status: 'idle' });
  };

  try {
    recognition.start();
    recognitionRef = recognition;
    listening = true;
    broadcast({ phase: 'status', status: 'listening' });
  } catch (err) {
    listening = false;
    recognitionRef = null;
    const message = err instanceof Error ? err.message : 'start_failed';
    broadcast({ phase: 'status', status: 'error', error: message });
  }
}
