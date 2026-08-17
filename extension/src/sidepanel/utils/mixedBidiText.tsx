/**
 * mixedBidiText — render Hebrew/English mixes without scrambled word order.
 *
 * Latin tokens (slugs, i18n, file.py) are wrapped in <bdi dir="ltr"> so they stay
 * readable inside RTL Hebrew sentences.
 */
import { Fragment, type ElementType } from 'react';

/** Quoted English phrases or Latin tokens (slugs, file.py). */
const LTR_ISLAND = /"[^"]*"|'[^']*'|[A-Za-z0-9][A-Za-z0-9_+.-]*/;

function splitMixedRuns(text: string): string[] {
  const parts: string[] = [];
  let rest = text;
  while (rest.length > 0) {
    const match = rest.match(LTR_ISLAND);
    if (!match || match.index === undefined) {
      parts.push(rest);
      break;
    }
    if (match.index > 0) parts.push(rest.slice(0, match.index));
    parts.push(match[0]);
    rest = rest.slice(match.index + match[0].length);
  }
  return parts.filter((p) => p.length > 0);
}

function isLtrIsland(part: string): boolean {
  return LTR_ISLAND.test(part);
}

function isCodeLikeToken(part: string): boolean {
  return /^[A-Za-z0-9][A-Za-z0-9_+.-]*$/.test(part);
}

interface MixedBidiTextProps {
  text: string;
  className?: string;
  as?: ElementType;
}

export function MixedBidiText({ text, className = '', as: Tag = 'span' }: MixedBidiTextProps) {
  const parts = splitMixedRuns(text);
  return (
    <Tag dir="auto" className={`bidi-plaintext text-start ${className}`.trim()}>
      {parts.map((part, i) =>
        isLtrIsland(part) ? (
          <bdi
            key={i}
            dir="ltr"
            className={isCodeLikeToken(part) ? 'font-mono text-[0.92em]' : 'inline-block max-w-full'}
          >
            {part}
          </bdi>
        ) : (
          <Fragment key={i}>{part}</Fragment>
        ),
      )}
    </Tag>
  );
}
