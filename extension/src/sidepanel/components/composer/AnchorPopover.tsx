/**
 * AnchorPopover — portal + fixed positioning so menus aren't clipped by
 * overflow-hidden ancestors (Chat column above the composer).
 */
import { createPortal } from 'react-dom';
import { useLayoutEffect, useState, type ReactNode, type RefObject } from 'react';

interface AnchorPopoverProps {
  anchorRef: RefObject<HTMLElement | null>;
  popoverRef?: RefObject<HTMLDivElement | null>;
  open: boolean;
  children: ReactNode;
  className?: string;
  /** Preferred width in px */
  width?: number;
  minWidth?: number;
}

export function AnchorPopover({
  anchorRef,
  popoverRef,
  open,
  children,
  className = '',
  width = 272,
  minWidth = 224,
}: AnchorPopoverProps) {
  const [pos, setPos] = useState<{ left: number; bottom: number; w: number } | null>(null);

  useLayoutEffect(() => {
    if (!open) {
      setPos(null);
      return;
    }

    const update = (): void => {
      const el = anchorRef.current;
      if (!el) return;
      const rect = el.getBoundingClientRect();
      const margin = 8;
      const w = Math.min(width, window.innerWidth - margin * 2);
      let left = rect.left;
      if (left + w > window.innerWidth - margin) {
        left = Math.max(margin, window.innerWidth - margin - w);
      }
      setPos({
        left,
        bottom: window.innerHeight - rect.top + 4,
        w,
      });
    };

    update();
    window.addEventListener('resize', update);
    window.addEventListener('scroll', update, true);
    return () => {
      window.removeEventListener('resize', update);
      window.removeEventListener('scroll', update, true);
    };
  }, [open, anchorRef, width]);

  if (!open || !pos) return null;

  return createPortal(
    <div
      ref={popoverRef}
      className={className}
      style={{
        position: 'fixed',
        left: pos.left,
        bottom: pos.bottom,
        width: pos.w,
        minWidth: Math.min(minWidth, pos.w),
        zIndex: 10000,
      }}
    >
      {children}
    </div>,
    document.body,
  );
}
