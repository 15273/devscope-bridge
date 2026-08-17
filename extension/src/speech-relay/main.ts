/**
 * speech-relay — STT in a hidden iframe (allow="microphone") inside the side panel.
 * Chrome blocks mic + SpeechRecognition in the panel document itself.
 */
import {
  getSpeechRecognitionCtor,
  type SpeechRecognitionErrorEvent,
  type SpeechRecognitionInstance,
  type SpeechRecognitionResultEvent,
} from '@/shared/speech/speechRecognition';

const PARENT_ORIGIN = location.origin;

type SttStatus = 'idle' | 'listening' | 'unsupported' | 'denied' | 'error';

let recognitionRef: SpeechRecognitionInstance | null = null;
let listening = false;
let generation = 0;

function postToParent(payload: Record<string, unknown>): void {
  window.parent.postMessage({ source: 'devscope-speech-relay', ...payload }, PARENT_ORIGIN);
}

async function primeMic(): Promise<boolean> {
  if (!navigator.mediaDevices?.getUserMedia) return true;
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    for (const track of stream.getTracks()) track.stop();
    return true;
  } catch {
    return false;
  }
}

function stopRecognition(): void {
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
  postToParent({ phase: 'status', status: 'idle' as SttStatus });
}

async function startRecognition(lang: string): Promise<void> {
  const Ctor = getSpeechRecognitionCtor();
  if (!Ctor) {
    postToParent({ phase: 'status', status: 'unsupported' as SttStatus });
    return;
  }

  const micOk = await primeMic();
  if (!micOk) {
    postToParent({ phase: 'status', status: 'denied' as SttStatus, error: 'mic_denied' });
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
    if (trimmed) postToParent({ phase: 'transcript', text: trimmed });
  };

  recognition.onerror = (event: SpeechRecognitionErrorEvent) => {
    if (gen !== generation) return;
    const code = event.error ?? 'unknown';
    if (code === 'not-allowed' || code === 'service-not-allowed') {
      listening = false;
      recognitionRef = null;
      postToParent({ phase: 'status', status: 'denied' as SttStatus, error: code });
      return;
    }
    if (code === 'aborted' || code === 'no-speech') return;
    listening = false;
    recognitionRef = null;
    postToParent({ phase: 'status', status: 'error' as SttStatus, error: code });
  };

  recognition.onend = () => {
    if (gen !== generation) return;
    if (listening && recognitionRef === recognition) {
      try {
        recognition.start();
      } catch {
        listening = false;
        recognitionRef = null;
        postToParent({ phase: 'status', status: 'idle' as SttStatus });
      }
      return;
    }
    postToParent({ phase: 'status', status: 'idle' as SttStatus });
  };

  try {
    recognition.start();
    recognitionRef = recognition;
    listening = true;
    postToParent({ phase: 'status', status: 'listening' as SttStatus });
  } catch (err) {
    listening = false;
    recognitionRef = null;
    const message = err instanceof Error ? err.message : 'start_failed';
    postToParent({ phase: 'status', status: 'error' as SttStatus, error: message });
  }
}

window.addEventListener('message', (event) => {
  if (event.origin !== PARENT_ORIGIN) return;
  const data = event.data as { type?: string; lang?: string };
  if (data?.type === 'stt_start') {
    void startRecognition(data.lang ?? 'he-IL');
  } else if (data?.type === 'stt_stop') {
    stopRecognition();
  }
});

postToParent({
  phase: 'ready',
  supported: Boolean(getSpeechRecognitionCtor()),
});
