/**
 * ContextChips — staged page context above the composer (elements + attachments).
 */
import { Activity, Camera, Image as ImageIcon, Info, Layers, Terminal, X } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import type { ElementContext, PageAttachment, PageAttachmentKind } from '@/shared/frames';
import { ElementContextPreview } from './ElementContextPreview';

const ATTACHMENT_ICON: Record<PageAttachmentKind, LucideIcon> = {
  screenshot: Camera,
  snapshot: Layers,
  console: Terminal,
  network: Activity,
  page_info: Info,
  image: ImageIcon,
};

interface ContextChipsProps {
  elements: ElementContext[];
  attachments: PageAttachment[];
  annotating?: boolean;
  onRemoveElement: (index: number) => void;
  onRemoveAttachment: (index: number) => void;
  onStopAnnotating?: () => void;
}

export function ContextChips({
  elements,
  attachments,
  annotating = false,
  onRemoveElement,
  onRemoveAttachment,
  onStopAnnotating,
}: ContextChipsProps) {
  if (elements.length === 0 && attachments.length === 0 && !annotating) return null;

  return (
    <div className="space-y-1 pb-2">
      {(elements.length > 0 || annotating) && (
        <div className="flex items-center justify-between gap-2">
          <p className="text-2xs font-medium uppercase tracking-wider text-fg-subtle">
            {elements.length > 0
              ? `✏ ${elements.length} annotation${elements.length === 1 ? '' : 's'} staged`
              : '✏ Pick elements on the page'}
          </p>
          {annotating && onStopAnnotating && (
            <button
              type="button"
              onClick={onStopAnnotating}
              className="text-2xs font-medium text-signal transition-colors duration-fast ease-tool hover:text-signal-hover"
            >
              Done picking
            </button>
          )}
        </div>
      )}

      {annotating && elements.length === 0 && (
        <p className="text-2xs text-fg-muted">
          Click elements on the page, write a note below each one, then Attach to message.
        </p>
      )}

      {elements.map((el, i) => (
        <ElementContextPreview
          key={el.editRef ?? `${el.selector}-${i}`}
          element={el}
          index={i}
          onRemove={() => onRemoveElement(i)}
        />
      ))}

      {attachments.length > 0 && (
        <div className="flex flex-wrap gap-1 pt-0.5">
          {attachments.map((att, i) =>
            att.kind === 'image' && typeof att.data === 'string' ? (
              <ImageChip
                key={`att-${i}-image`}
                src={att.data}
                label={att.label}
                onRemove={() => onRemoveAttachment(i)}
              />
            ) : (
              <AttachmentChip
                key={`att-${i}-${att.kind}`}
                icon={ATTACHMENT_ICON[att.kind] ?? Info}
                label={att.label}
                title={att.url ?? att.kind}
                onRemove={() => onRemoveAttachment(i)}
              />
            ),
          )}
        </div>
      )}
    </div>
  );
}

interface AttachmentChipProps {
  icon: LucideIcon;
  label: string;
  title?: string;
  onRemove: () => void;
}

interface ImageChipProps {
  src: string;
  label: string;
  onRemove: () => void;
}

/** Image attachment chip with a thumbnail preview of the pasted/uploaded image. */
function ImageChip({ src, label, onRemove }: ImageChipProps) {
  return (
    <span
      title={label}
      className="group inline-flex items-center gap-1 rounded-sm border border-line bg-surface py-0.5 pl-0.5 pr-1.5 text-2xs text-fg-muted"
    >
      <img
        src={src}
        alt={label}
        className="h-7 w-7 flex-shrink-0 rounded-xs object-cover"
      />
      <span className="max-w-[110px] truncate">{label}</span>
      <button
        type="button"
        onClick={onRemove}
        aria-label={`Remove ${label}`}
        className="flex-shrink-0 rounded text-fg-subtle transition-colors duration-fast ease-tool hover:text-danger"
      >
        <X size={11} strokeWidth={2.5} />
      </button>
    </span>
  );
}

function AttachmentChip({ icon: Icon, label, title, onRemove }: AttachmentChipProps) {
  return (
    <span
      title={title}
      className="group inline-flex max-w-[160px] items-center gap-1 rounded-sm border border-line bg-surface px-1.5 py-1 text-2xs text-fg-muted"
    >
      <Icon size={11} strokeWidth={2} className="flex-shrink-0 text-fg-subtle" />
      <span className="truncate">{label}</span>
      <button
        type="button"
        onClick={onRemove}
        aria-label={`Remove ${label}`}
        className="flex-shrink-0 rounded text-fg-subtle transition-colors duration-fast ease-tool hover:text-danger"
      >
        <X size={11} strokeWidth={2.5} />
      </button>
    </span>
  );
}
