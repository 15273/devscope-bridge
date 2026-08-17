/** Plain text from markdown-ish assistant replies for speechSynthesis. */
export function stripMarkdownForSpeech(text: string): string {
  let plain = text.replace(/\\n/g, '\n').replace(/\\"/g, '"');
  plain = plain.replace(/\[([^\]]+)\]\([^)]+\)/g, '$1');
  plain = plain.replace(/!\[([^\]]*)\]\([^)]+\)/g, '$1');
  plain = plain.replace(/```[\s\S]*?```/g, ' ');
  plain = plain.replace(/`([^`]+)`/g, '$1');
  plain = plain.replace(/^#{1,6}\s+/gm, '');
  plain = plain.replace(/[*_~]/g, '');
  plain = plain.replace(/\n+/g, '. ');
  plain = plain.replace(/\s+/g, ' ').trim();
  return plain;
}

const MAX_CHUNK = 280;

export function chunkTextForSpeech(plain: string, maxLen = MAX_CHUNK): string[] {
  if (!plain) return [];
  if (plain.length <= maxLen) return [plain];

  const sentences = plain.match(/[^.!?]+[.!?]+|[^.!?]+$/g) ?? [plain];
  const chunks: string[] = [];
  let buf = '';

  for (const sentence of sentences) {
    const part = sentence.trim();
    if (!part) continue;
    if (`${buf} ${part}`.trim().length <= maxLen) {
      buf = buf ? `${buf} ${part}` : part;
    } else {
      if (buf) chunks.push(buf);
      if (part.length <= maxLen) {
        buf = part;
      } else {
        for (let i = 0; i < part.length; i += maxLen) {
          chunks.push(part.slice(i, i + maxLen));
        }
        buf = '';
      }
    }
  }
  if (buf) chunks.push(buf);
  return chunks;
}
