/**
 * CockpitShell — three-pane layout for WhatsApp and Email cockpits.
 *
 * Layout: [list pane] | [reader pane] | [AI assist pane]
 * The assist pane collapses below 520 px (narrow extension panel widths).
 * Pure layout — no data. All content comes from props.
 */
import type { ReactNode } from 'react';

interface CockpitShellProps {
  list: ReactNode;
  reader: ReactNode;
  assist: ReactNode;
}

export function CockpitShell({ list, reader, assist }: CockpitShellProps) {
  return (
    <div className="flex min-h-0 flex-1 overflow-hidden">
      {/* List pane */}
      <div className="flex w-[160px] shrink-0 flex-col overflow-y-auto border-e border-line bg-surface">
        {list}
      </div>

      {/* Reader pane */}
      <div className="flex min-w-0 flex-1 flex-col overflow-y-auto bg-surface">
        {reader}
      </div>

      {/* Assist pane — hidden on narrow widths (<520px) */}
      <div className="hidden w-[160px] shrink-0 flex-col overflow-y-auto border-s border-line bg-surface-raised min-[520px]:flex">
        {assist}
      </div>
    </div>
  );
}
