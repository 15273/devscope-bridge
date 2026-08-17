/**
 * SetupGuide — the canonical "how to connect DevScope" steps.
 *
 * Used by first-run Onboarding and by Settings (so it's always reachable). The
 * start command is pre-filled with THIS extension's real id (chrome.runtime.id)
 * so the bridge's CORS allowlist trusts it — copy-paste, no editing.
 */
import { useCallback, useState } from 'react';
import { Check, Copy } from 'lucide-react';
import { BRIDGE_INSTALL_CMD, BRIDGE_TOKEN_PATH } from '../bridge';

function extensionId(): string {
  try {
    return chrome.runtime?.id ?? '<extension-id>';
  } catch {
    return '<extension-id>';
  }
}

function startCommand(): string {
  return `BRIDGE_EXTENSION_ID="chrome-extension://${extensionId()}" devscope-bridge`;
}

export function SetupGuide() {
  return (
    <div className="w-full max-w-[300px] space-y-3 text-left">
      <Step n={1} title="Install the Claude CLI">
        <p className="text-xs leading-relaxed text-fg-muted">
          DevScope drives your local <span className="font-medium text-fg">claude</span> CLI (Cursor
          optional). Make sure it's installed and logged in.
        </p>
      </Step>
      <Step n={2} title="Install the bridge (once)">
        <CommandLine command={BRIDGE_INSTALL_CMD} />
      </Step>
      <Step n={3} title="Start the bridge">
        <p className="mb-1.5 text-xs leading-relaxed text-fg-muted">
          This command already includes your extension ID, so the bridge will trust this extension:
        </p>
        <CommandLine command={startCommand()} />
      </Step>
      <Step n={4} title="Paste your token into Settings">
        <p className="text-xs leading-relaxed text-fg-muted">
          The bridge prints a token on startup (also at{' '}
          <code className="rounded-sm bg-surface-overlay px-1 font-mono text-fg">
            {BRIDGE_TOKEN_PATH}
          </code>
          ). Paste it into the Connection field above and hit Test connection.
        </p>
      </Step>
    </div>
  );
}

function Step({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-2.5">
      <span className="flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full bg-surface-overlay text-2xs font-semibold text-fg-muted">
        {n}
      </span>
      <div className="min-w-0 flex-1 space-y-1.5">
        <p className="text-xs font-medium text-fg">{title}</p>
        {children}
      </div>
    </div>
  );
}

export function CommandLine({ command }: { command: string }) {
  const [copied, setCopied] = useState(false);
  const copy = useCallback(() => {
    navigator.clipboard
      .writeText(command)
      .then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      })
      .catch(() => {});
  }, [command]);

  return (
    <div className="flex items-center gap-2 rounded-md border border-line bg-surface-overlay px-2.5 py-1.5">
      <code className="flex-1 truncate font-mono text-xs text-fg" title={command}>
        <span className="select-none text-fg-subtle">$ </span>
        {command}
      </code>
      <button
        onClick={copy}
        aria-label="Copy command"
        className="flex-shrink-0 rounded p-0.5 text-fg-subtle transition-colors duration-fast ease-tool hover:bg-surface-raised hover:text-fg"
      >
        {copied ? <Check size={13} strokeWidth={2.5} className="text-success" /> : <Copy size={13} strokeWidth={2} />}
      </button>
    </div>
  );
}
