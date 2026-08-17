const HEBREW_RE = /[\u0590-\u05FF]/;

/** Map UI language code (he/en/…) to Web Speech API BCP-47 tag. */
export function speechLocaleFromPreference(pref: string): string {
  const p = pref.toLowerCase().trim();
  if (p === 'he' || p.startsWith('he')) return 'he-IL';
  if (p === 'fr' || p.startsWith('fr')) return 'fr-FR';
  if (p === 'de' || p.startsWith('de')) return 'de-DE';
  if (p === 'en' || p.startsWith('en')) return 'en-US';
  return 'he-IL';
}

/**
 * Pick he-IL or en-US from message text; when empty, use user dictation preference
 * (not browser UI language — Chrome is often en-GB even for Hebrew speakers).
 */
export function resolveSpeechLocale(sampleText?: string, preference = 'he'): string {
  const trimmed = sampleText?.trim() ?? '';
  if (trimmed && HEBREW_RE.test(trimmed)) return 'he-IL';
  if (trimmed && /[a-zA-Z]/.test(trimmed)) return 'en-US';
  return speechLocaleFromPreference(preference);
}
