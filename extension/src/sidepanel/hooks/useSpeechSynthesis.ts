/**
 * Browser TTS for assistant replies (speechSynthesis).
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { chunkTextForSpeech, stripMarkdownForSpeech } from '../utils/speech/speechText';
import { resolveSpeechLocale } from '../utils/speech/speechLocale';
import {
  attachSpeechErrorHandler,
  ensureSpeechVoicesLoaded,
  getActiveSpeechOwner,
  isSpeechSynthesisSupported,
  primeSpeechSynthesisFromUserGesture,
  resolveVoiceForSpeech,
  scheduleSpeechSynthesisStart,
  setActiveSpeechOwner,
  startSpeechSynthesisKeepAlive,
  stopSpeechSynthesisKeepAlive,
} from '../utils/speech/speechSynthesisCompat';

export function isBrowserTtsSupported(): boolean {
  return isSpeechSynthesisSupported();
}

export function useSpeechSynthesis(ownerId: string, sampleText?: string) {
  const lang = resolveSpeechLocale(sampleText);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [isSupported, setIsSupported] = useState(false);
  const voicesRef = useRef<SpeechSynthesisVoice[]>([]);
  const cancelledRef = useRef(false);

  useEffect(() => {
    if (!isSpeechSynthesisSupported()) return;

    const loadVoices = async () => {
      voicesRef.current = await ensureSpeechVoicesLoaded();
      setIsSupported(true);
    };

    void loadVoices();
    const onChange = () => {
      voicesRef.current = window.speechSynthesis.getVoices();
      setIsSupported(true);
    };
    window.speechSynthesis.addEventListener('voiceschanged', onChange);
    return () => window.speechSynthesis.removeEventListener('voiceschanged', onChange);
  }, []);

  const stop = useCallback(() => {
    cancelledRef.current = true;
    if (getActiveSpeechOwner() === ownerId) setActiveSpeechOwner(null);
    window.speechSynthesis.cancel();
    stopSpeechSynthesisKeepAlive();
    setIsSpeaking(false);
  }, [ownerId]);

  useEffect(() => {
    return () => {
      if (getActiveSpeechOwner() === ownerId) {
        window.speechSynthesis.cancel();
        setActiveSpeechOwner(null);
        stopSpeechSynthesisKeepAlive();
      }
    };
  }, [ownerId]);

  const speak = useCallback(
    async (rawText: string) => {
      if (!isSpeechSynthesisSupported()) return;

      primeSpeechSynthesisFromUserGesture();
      voicesRef.current = await ensureSpeechVoicesLoaded();

      const locale = resolveSpeechLocale(rawText);
      const plain = stripMarkdownForSpeech(rawText);
      const chunks = chunkTextForSpeech(plain);
      if (!chunks.length) return;

      const prevOwner = getActiveSpeechOwner();
      if (prevOwner && prevOwner !== ownerId) {
        window.speechSynthesis.cancel();
      }
      setActiveSpeechOwner(ownerId);
      cancelledRef.current = false;
      setIsSpeaking(true);
      startSpeechSynthesisKeepAlive();

      const voice = resolveVoiceForSpeech(voicesRef.current, locale);
      let index = 0;

      const speakNext = () => {
        if (cancelledRef.current || getActiveSpeechOwner() !== ownerId) {
          setIsSpeaking(false);
          stopSpeechSynthesisKeepAlive();
          return;
        }
        if (index >= chunks.length) {
          setIsSpeaking(false);
          if (getActiveSpeechOwner() === ownerId) setActiveSpeechOwner(null);
          stopSpeechSynthesisKeepAlive();
          return;
        }

        const utterance = new SpeechSynthesisUtterance(chunks[index]);
        index += 1;
        utterance.lang = locale;
        if (voice) utterance.voice = voice;
        utterance.rate = 1;
        utterance.pitch = 1;

        utterance.onend = speakNext;
        attachSpeechErrorHandler(utterance, () => {
          setIsSpeaking(false);
          if (getActiveSpeechOwner() === ownerId) setActiveSpeechOwner(null);
          stopSpeechSynthesisKeepAlive();
        });

        window.speechSynthesis.speak(utterance);
      };

      scheduleSpeechSynthesisStart(speakNext);
    },
    [ownerId],
  );

  const toggle = useCallback(
    (text: string) => {
      if (isSpeaking) stop();
      else void speak(text);
    },
    [isSpeaking, speak, stop],
  );

  return { isSupported, isSpeaking, lang, speak, stop, toggle };
}
