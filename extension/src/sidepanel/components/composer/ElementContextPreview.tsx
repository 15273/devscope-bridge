/**
 * ElementContextPreview — compact read-only card for a picked page element.
 * Used in composer staging area and in sent user message bubbles.
 */
import type { ElementContext } from '@/shared/frames';

function truncate(text: string, max: number): string {
  if (text.length <= max) return text;
  return `${text.slice(0, max - 1)}…`;
}

interface ElementContextPreviewProps {
  element: ElementContext;
  index: number;
  compact?: boolean;
  onRemove?: () => void;
}

export function ElementContextPreview({
  element,
  index,
  compact = false,
  onRemove,
}: ElementContextPreviewProps) {
  const ariaLabel = element.ariaName?.trim() || element.text?.trim() || '';
  const role = element.ariaRole?.trim() || null;
  const note = element.note?.trim() || '';

  return (
    <div
      className={`overflow-hidden rounded-md border border-line bg-surface-overlay ${
        compact ? 'text-2xs' : ''
      }`}
    >
      <div className={`flex gap-2 ${compact ? 'p-1.5' : 'p-2'}`}>
        {element.screenshotSnippet && (
          <img
            src={element.screenshotSnippet}
            alt=""
            className={`flex-shrink-0 rounded-sm border border-line object-cover ${
              compact ? 'h-10 w-10' : 'h-14 w-14'
            }`}
          />
        )}
        <div className="min-w-0 flex-1">
          <div className="flex items-start gap-1.5">
            <span className="flex h-4 w-4 flex-shrink-0 items-center justify-center rounded-full bg-signal font-mono text-[9px] font-semibold text-signal-contrast">
              {index + 1}
            </span>
            <div className="min-w-0 flex-1 space-y-0.5">
              <div className="flex flex-wrap items-center gap-1">
                <span className="font-mono text-2xs text-signal">{`<${element.tag}>`}</span>
                {role && (
                  <span className="rounded-sm border border-line bg-surface px-1 py-0.5 font-mono text-[9px] uppercase text-fg-subtle">
                    role={role}
                  </span>
                )}
              </div>
              {ariaLabel && (
                <p className="truncate text-2xs text-fg" title={ariaLabel}>
                  “{truncate(ariaLabel, compact ? 48 : 80)}”
                </p>
              )}
              <p className="truncate font-mono text-[10px] text-fg-muted" title={element.selector}>
                {truncate(element.selector, compact ? 64 : 96)}
              </p>
              {note && (
                <p className="text-2xs text-fg" dir="auto">
                  <span className="text-fg-subtle">→ </span>
                  {note}
                </p>
              )}
            </div>
            {onRemove && (
              <button
                type="button"
                onClick={onRemove}
                aria-label="Remove annotation"
                className="flex-shrink-0 rounded px-1 text-fg-subtle transition-colors duration-fast ease-tool hover:text-danger"
              >
                ×
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

interface AttachedElementsListProps {
  elements: ElementContext[];
  compact?: boolean;
}

/** Stack of element previews for a sent user message. */
export function AttachedElementsList({ elements, compact = true }: AttachedElementsListProps) {
  if (elements.length === 0) return null;
  return (
    <div className={`space-y-1 ${compact ? 'mt-1.5' : ''}`}>
      {elements.map((el, i) => (
        <ElementContextPreview key={el.editRef ?? `${el.selector}-${i}`} element={el} index={i} compact={compact} />
      ))}
    </div>
  );
}
