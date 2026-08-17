/**
 * SlashMenu — autocomplete popover for `/` commands (native + custom).
 *
 * Presentational: the Composer owns filtering and keyboard navigation and passes
 * the filtered items + active index.
 *
 * Disabled commands (interactive-terminal-only stubs) are rendered greyed-out
 * and cannot be selected — pressing Enter on them shows their `note` instead.
 */
import { useEffect, useRef } from 'react';
import type { SlashCommand } from '../../bridge';

interface SlashMenuProps {
  items: SlashCommand[];
  activeIndex: number;
  onSelect: (cmd: SlashCommand) => void;
}

const SOURCE_LABEL: Record<SlashCommand['source'], string> = {
  native: 'DevScope',
  builtin: 'built-in',
  project: 'project',
  user: 'user',
  skill: 'skill',
};

export function SlashMenu({ items, activeIndex, onSelect }: SlashMenuProps) {
  const activeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    activeRef.current?.scrollIntoView({ block: 'nearest' });
  }, [activeIndex]);

  if (items.length === 0) return null;

  return (
    <div className="absolute bottom-full left-0 right-0 z-[100] mb-1 overflow-hidden rounded-md border border-line bg-surface-overlay shadow-modal dark:shadow-modal-dark">
      <div className="max-h-56 overflow-y-auto py-1">
        {items.map((cmd, i) => {
          const isActive = i === activeIndex;
          const isDisabled = cmd.disabled === true;
          return (
            <button
              key={cmd.name}
              ref={isActive ? activeRef : null}
              type="button"
              disabled={isDisabled}
              onMouseDown={(e) => {
                e.preventDefault();
                if (!isDisabled) onSelect(cmd);
              }}
              className={`flex w-full items-center gap-2 px-2.5 py-1.5 text-left transition-colors duration-fast ease-tool ${
                isDisabled
                  ? 'cursor-not-allowed opacity-45'
                  : isActive
                    ? 'bg-surface-raised'
                    : 'hover:bg-surface-raised/60'
              }`}
            >
              <span className={`font-mono text-sm font-medium ${isDisabled ? 'text-fg-subtle' : 'text-fg'}`}>
                {cmd.name}
              </span>
              <span className="min-w-0 flex-1 truncate text-2xs text-fg-subtle">
                {isDisabled ? (cmd.note ?? 'terminal only') : cmd.description}
              </span>
              {!isDisabled && cmd.parallel && (
                <span className="flex-shrink-0 rounded-sm bg-signal-subtle px-1 text-[10px] text-signal">
                  parallel ⇉
                </span>
              )}
              {isDisabled && (
                <span className="flex-shrink-0 rounded-sm bg-surface px-1 text-[10px] text-fg-subtle opacity-60">
                  terminal only
                </span>
              )}
              {!isDisabled && (
                <span className="flex-shrink-0 rounded-sm bg-surface px-1 text-[10px] uppercase tracking-wide text-fg-subtle">
                  {SOURCE_LABEL[cmd.source]}
                </span>
              )}
            </button>
          );
        })}
      </div>
      <div className="border-t border-line px-2.5 py-1 text-[10px] text-fg-subtle">
        ↑↓ navigate · ↵ select · esc close
      </div>
    </div>
  );
}
