export type PersonaVoiceGender = 'female' | 'male' | 'other';

function scoreEnglish(voice: SpeechSynthesisVoice): number {
  const lang = voice.lang.toLowerCase();
  const name = voice.name.toLowerCase();
  let score = lang.startsWith('en-us') ? 10 : lang.startsWith('en') ? 5 : 0;
  if (name.includes('google')) score += 8;
  if (voice.default) score += 3;
  return score;
}

function scoreHebrew(voice: SpeechSynthesisVoice): number {
  const lang = voice.lang.toLowerCase();
  let score = lang.startsWith('he-il') ? 10 : lang.startsWith('he') ? 5 : 0;
  if (voice.default) score += 3;
  return score;
}

export function pickVoiceForLocale(
  voices: SpeechSynthesisVoice[],
  locale: string,
): SpeechSynthesisVoice | undefined {
  if (!voices.length) return undefined;
  const lang = locale.toLowerCase();

  if (lang.startsWith('he')) {
    const he = voices.filter((v) => v.lang.toLowerCase().startsWith('he'));
    if (!he.length) return voices.find((v) => v.default) ?? voices[0];
    return [...he].sort((a, b) => scoreHebrew(b) - scoreHebrew(a))[0];
  }

  const en = voices.filter((v) => v.lang.toLowerCase().startsWith('en'));
  if (!en.length) return voices.find((v) => v.default) ?? voices[0];
  return [...en].sort((a, b) => scoreEnglish(b) - scoreEnglish(a))[0];
}
