/**
 * AiAssistPanel — cockpit assist actions + streamed output area.
 */

interface AiAssistAction {
  label: string;
  onClick: () => void;
}

interface AiAssistPanelProps {
  actions: AiAssistAction[];
  /** Latest streamed assist output (Phase 2 wiring). */
  outputText?: string;
  isStreaming?: boolean;
}

export function AiAssistPanel({ actions, outputText, isStreaming }: AiAssistPanelProps) {
  return (
    <div className="flex flex-1 flex-col gap-2 p-2">
      <div className="flex flex-col gap-1">
        {actions.map((action) => (
          <button
            key={action.label}
            type="button"
            onClick={action.onClick}
            className="w-full rounded-[5px] border border-line bg-surface px-2 py-1.5 text-left text-2xs font-medium text-fg-muted transition-colors duration-fast ease-tool hover:bg-surface-overlay hover:text-fg"
          >
            {action.label}
          </button>
        ))}
      </div>

      <div className="mt-1 min-h-[60px] flex-1 overflow-y-auto rounded-[5px] border border-line bg-surface-overlay p-2 text-2xs text-fg-subtle">
        {outputText ? (
          <pre className="whitespace-pre-wrap font-sans text-fg">{outputText}</pre>
        ) : (
          <span className="text-fg-subtle">Assist output will appear here when an action runs.</span>
        )}
        {isStreaming && <span className="ml-0.5 text-signal animate-cursor-pulse">▌</span>}
      </div>
    </div>
  );
}
