export type SpeechRecognitionCtor = new () => SpeechRecognitionInstance;

export interface SpeechRecognitionInstance extends EventTarget {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  maxAlternatives: number;
  start(): void;
  stop(): void;
  abort(): void;
  onresult: ((event: SpeechRecognitionResultEvent) => void) | null;
  onerror: ((event: SpeechRecognitionErrorEvent) => void) | null;
  onend: (() => void) | null;
}

export interface SpeechRecognitionResultEvent extends Event {
  resultIndex: number;
  results: SpeechRecognitionResultList;
}

export interface SpeechRecognitionErrorEvent extends Event {
  error: string;
  message?: string;
}

export function getSpeechRecognitionCtor(): SpeechRecognitionCtor | null {
  if (typeof window === 'undefined') return null;
  const w = window as Window & {
    SpeechRecognition?: SpeechRecognitionCtor;
    webkitSpeechRecognition?: SpeechRecognitionCtor;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export function isSpeechRecognitionSupported(): boolean {
  return getSpeechRecognitionCtor() !== null;
}

/** Prime mic permission path on Safari — call inside a click handler. */
export function primeSpeechRecognitionFromUserGesture(lang: string): void {
  const Ctor = getSpeechRecognitionCtor();
  if (!Ctor) return;
  try {
    const rec = new Ctor();
    rec.lang = lang;
    rec.onerror = () => {};
    rec.onend = () => {};
    rec.start();
    rec.stop();
  } catch {
    /* permission probe only */
  }
}
