/**
 * terminalBidi.ts — reorder PTY output for LTR xterm grids (Hebrew + English).
 *
 * xterm.js has no Unicode BiDi support (xtermjs/xterm.js#701). Logical-order RTL
 * text appears character-reversed in the terminal. We apply UAX #9 reordering on
 * complete lines while preserving ANSI escape sequences.
 */
import bidiFactory from 'bidi-js';

const bidi = bidiFactory();

/** Hebrew, Arabic, and related RTL scripts. */
const RTL_CHAR =
  /[\u0590-\u05FF\u0600-\u06FF\u0700-\u074F\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]/;

/** CSI / OSC / single-char escapes — kept in place during reorder. */
/* eslint-disable no-control-regex */
const ANSI_SEGMENT =
  /(\x1b\[[0-9:;<=>?]*[!-~]*|\x1b\][^\x07]*(?:\x07|\x1b\\)?|\x1b[^[\]])/g;
/* eslint-enable no-control-regex */

export function containsRtlText(text: string): boolean {
  return RTL_CHAR.test(text);
}

/** Logical → visual for an LTR terminal cell grid (paragraph base direction LTR). */
export function reorderBidiLogicalToVisual(text: string): string {
  if (!containsRtlText(text)) return text;

  const embeddingLevels = bidi.getEmbeddingLevels(text, 'ltr');
  const chars = [...text];
  const flips = bidi.getReorderSegments(text, embeddingLevels);
  for (const [start, end] of flips) {
    let i = start;
    let j = end;
    while (i < j) {
      const tmp = chars[i];
      chars[i] = chars[j];
      chars[j] = tmp;
      i += 1;
      j -= 1;
    }
  }
  const mirrored = bidi.getMirroredCharactersMap(text, embeddingLevels);
  mirrored.forEach((replacement, index) => {
    chars[index] = replacement;
  });
  return chars.join('');
}

function stripTrailingCr(line: string): string {
  const idx = line.lastIndexOf('\r');
  return idx >= 0 ? line.slice(idx + 1) : line;
}

/** Reorder visible text runs on one line; leave ANSI sequences untouched. */
export function reorderTerminalLine(line: string): string {
  if (!containsRtlText(line)) return line;
  const parts = line.split(ANSI_SEGMENT);
  return parts
    .map((part) => {
      if (!part || part.startsWith('\x1b') || !containsRtlText(part)) return part;
      return reorderBidiLogicalToVisual(part);
    })
    .join('');
}

/**
 * Buffer PTY chunks and BiDi-process on newline boundaries so escape codes and
 * UTF-16 code units are never split mid-character.
 */
export class PtyBidiWriter {
  private pending = '';

  /** @returns text ready to pass to xterm.write() */
  push(chunk: string): string {
    if (!chunk) return '';
    this.pending += chunk;

    let out = '';
    for (;;) {
      const nl = this.pending.indexOf('\n');
      if (nl < 0) break;
      const rawLine = this.pending.slice(0, nl);
      this.pending = this.pending.slice(nl + 1);
      out += reorderTerminalLine(stripTrailingCr(rawLine)) + '\n';
    }
    return out;
  }

  /** Flush an incomplete line (e.g. on PTY exit). */
  flush(): string {
    if (!this.pending) return '';
    const line = reorderTerminalLine(stripTrailingCr(this.pending));
    this.pending = '';
    return line;
  }
}
