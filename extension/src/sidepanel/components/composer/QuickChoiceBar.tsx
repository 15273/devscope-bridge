/**
 * QuickChoiceBar — tap-to-send chips for numbered options in plain-text assistant replies.
 */
import type { NumberedChoice } from '../../utils/parseNumberedChoices';

interface QuickChoiceBarProps {
  choices: NumberedChoice[];
  disabled?: boolean;
  onPick: (replyText: string) => void;
}

function truncate(s: string, max = 48): string {
  return s.length <= max ? s : `${s.slice(0, max - 1)}…`;
}

export function QuickChoiceBar({ choices, disabled, onPick }: QuickChoiceBarProps) {
  if (choices.length < 2) return null;

  return (
    <div className="pb-1.5">
      <p className="mb-1 text-2xs text-fg-muted">
        {choices.every((c) => c.label === 'כן' || c.label === 'לא')
          ? 'Quick reply:'
          : 'Quick reply — pick an option:'}
      </p>
      <div className="flex flex-col gap-1">
        {choices.map((c) => (
          <button
            key={c.num}
            type="button"
            disabled={disabled}
            onClick={() => onPick(c.replyText)}
            className="rounded-md border border-signal/35 bg-surface px-2.5 py-1.5 text-left text-xs text-fg transition-colors duration-fast ease-tool hover:border-signal hover:bg-signal-subtle disabled:opacity-40"
          >
            <span className="font-semibold text-signal">{c.num}.</span>{' '}
            <span className="text-fg-muted">{truncate(c.label)}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
