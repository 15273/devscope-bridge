/**
 * SegmentedMessageBody — renders a turn-tagged assistant bubble's segments in
 * emission order: extended-thinking runs as ThinkingBlock, text runs as their
 * own MarkdownMessage block. Order matters — a real turn can interleave
 * think -> tool call (opens a new text block) -> think again, so segments are
 * walked in array order rather than grouped by kind. Grouping by kind (take
 * "the" thinking segment) silently drops every thinking run but the first.
 *
 * Only the segment at the very end of the array can still be open/streaming.
 * That isn't automatic from append order alone — turnSegments.ts enforces it:
 * appendTextDelta closes any still-open trailing thinking segment the moment
 * a new text segment opens, and markThinkingDone (called at turn DONE) closes
 * every open thinking segment, not just one. Without those, an earlier
 * thinking run stays open forever and renders as a stuck "חושב…". The
 * streaming cursor likewise only follows the last text segment.
 */
import type { TextSegment, TurnSegment } from '../store/turnSegments';
import { MarkdownMessage } from './MarkdownMessage';
import { StreamingCursor, StreamingPlaceholder } from './StreamingIndicators';
import { ThinkingBlock } from './ThinkingBlock';

interface SegmentedMessageBodyProps {
  segments: TurnSegment[];
  isStreaming: boolean;
  statusLabel?: string;
  runningTool?: string;
  queuedSteeringCount: number;
}

function findLastIndex<T>(items: T[], predicate: (item: T) => boolean): number {
  for (let i = items.length - 1; i >= 0; i -= 1) {
    if (predicate(items[i])) return i;
  }
  return -1;
}

export function SegmentedMessageBody({
  segments,
  isStreaming,
  statusLabel,
  runningTool,
  queuedSteeringCount,
}: SegmentedMessageBodyProps) {
  // No segments and no longer streaming: the turn produced nothing here. Render
  // nothing rather than a lone cursor that will never advance.
  if (segments.length === 0) {
    return isStreaming ? (
      <StreamingPlaceholder
        statusLabel={statusLabel}
        runningTool={runningTool}
        queuedSteeringCount={queuedSteeringCount}
      />
    ) : null;
  }

  const lastIndex = segments.length - 1;
  const lastTextIndex = findLastIndex(segments, (s) => s.kind === 'text');

  return (
    <>
      {segments.map((seg, i) =>
        seg.kind === 'thinking' ? (
          <ThinkingBlock
            key={`thinking-${i}`}
            text={seg.text}
            streaming={i === lastIndex && isStreaming && seg.doneAt === undefined}
            startedAt={seg.startedAt}
            doneAt={seg.doneAt}
          />
        ) : (
          // Keyed by array position, not blockIndex — the CLI restarts
          // content-block indices per assistant message within a turn, so
          // blockIndex is not guaranteed unique across a turn's segments
          // (see session_reader.py's per-session text-block counter for the
          // bridge-side half of this fix).
          <TextSegmentBlock key={`text-${i}`} segment={seg} isCursor={isStreaming && i === lastTextIndex} />
        ),
      )}
    </>
  );
}

function TextSegmentBlock({ segment, isCursor }: { segment: TextSegment; isCursor: boolean }) {
  return (
    <div>
      <MarkdownMessage text={segment.text} isStreaming={isCursor} />
      {isCursor && <StreamingCursor />}
    </div>
  );
}
