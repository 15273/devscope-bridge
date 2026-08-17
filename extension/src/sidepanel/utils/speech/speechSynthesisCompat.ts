import { pickVoiceForLocale } from './speechVoicePicker';

export function isSpeechSynthesisSupported(): boolean {
  return typeof window !== 'undefined' && 'speechSynthesis' in window;
}

function isSafariLikeBrowser(): boolean {
  if (typeof navigator === 'undefined') return false;
  const ua = navigator.userAgent;
  const isSafari = /Safari/i.test(ua) && !/Chrome|Chromium|CriOS|Edg|OPR|Android/i.test(ua);
  const isIOS = /iPhone|iPad|iPod/i.test(ua);
  return isSafari || isIOS;
}

let keepAliveTimer: ReturnType<typeof setInterval> | null = null;

export function startSpeechSynthesisKeepAlive(): void {
  if (!isSafariLikeBrowser() || !isSpeechSynthesisSupported()) return;
  if (keepAliveTimer) return;
  keepAliveTimer = setInterval(() => {
    const synth = window.speechSynthesis;
    if (synth.speaking && synth.paused) synth.resume();
  }, 8000);
}

export function stopSpeechSynthesisKeepAlive(): void {
  if (keepAliveTimer) {
    clearInterval(keepAliveTimer);
    keepAliveTimer = null;
  }
}

export function primeSpeechSynthesisFromUserGesture(): void {
  if (!isSpeechSynthesisSupported()) return;
  const synth = window.speechSynthesis;
  synth.getVoices();
  if (synth.paused) synth.resume();
  if (!isSafariLikeBrowser()) return;
  const prime = new SpeechSynthesisUtterance('\u200b');
  prime.volume = 0.01;
  prime.rate = 2;
  synth.speak(prime);
  synth.cancel();
}

export function scheduleSpeechSynthesisStart(run: () => void): void {
  if (!isSpeechSynthesisSupported()) {
    run();
    return;
  }
  const synth = window.speechSynthesis;
  if (synth.paused) synth.resume();
  if (isSafariLikeBrowser() && (synth.speaking || synth.pending)) {
    synth.cancel();
    window.setTimeout(run, 50);
    return;
  }
  synth.cancel();
  window.setTimeout(run, 0);
}

export function attachSpeechErrorHandler(
  utterance: SpeechSynthesisUtterance,
  onFatalError: () => void,
): void {
  utterance.onerror = (event) => {
    const err = (event as SpeechSynthesisErrorEvent).error;
    if (err === 'canceled' || err === 'interrupted') return;
    onFatalError();
  };
}

export function ensureSpeechVoicesLoaded(timeoutMs = 1200): Promise<SpeechSynthesisVoice[]> {
  if (!isSpeechSynthesisSupported()) return Promise.resolve([]);

  const synth = window.speechSynthesis;
  const existing = synth.getVoices();
  if (existing.length) return Promise.resolve(existing);

  return new Promise((resolve) => {
    let settled = false;
    const finish = (voices: SpeechSynthesisVoice[]) => {
      if (settled) return;
      settled = true;
      synth.removeEventListener('voiceschanged', onChange);
      resolve(voices);
    };

    const onChange = () => {
      const voices = synth.getVoices();
      if (voices.length) finish(voices);
    };

    synth.addEventListener('voiceschanged', onChange);
    synth.getVoices();
    window.setTimeout(() => finish(synth.getVoices()), timeoutMs);
  });
}

export function resolveVoiceForSpeech(
  voices: SpeechSynthesisVoice[],
  locale: string,
): SpeechSynthesisVoice | undefined {
  return pickVoiceForLocale(voices, locale);
}

let activeOwnerId: string | null = null;

export function getActiveSpeechOwner(): string | null {
  return activeOwnerId;
}

export function setActiveSpeechOwner(ownerId: string | null): void {
  activeOwnerId = ownerId;
}

export function stopAllSpeech(): void {
  if (!isSpeechSynthesisSupported()) return;
  activeOwnerId = null;
  window.speechSynthesis.cancel();
  stopSpeechSynthesisKeepAlive();
}

/** True only while our Listen button TTS is active (not speechSynthesis.speaking — often stuck in Chrome). */
export function isTtsPlaying(): boolean {
  return Boolean(activeOwnerId);
}
