/**
 * Onboarding — first-run setup shown when the bridge isn't reachable yet.
 *
 * Shows the full SetupGuide plus a live status row that advances on its own as
 * `useBridgeHealth` re-probes (bridge detected / waiting for a valid token).
 * When the runtime is down entirely, offers the one-line launchd installer.
 */
import { useState } from 'react';
import { Check, Copy, Loader2 } from 'lucide-react';
import type { BridgeHealth } from '../bridge';
import { Logomark } from './Logomark';
import { SetupGuide } from './SetupGuide';

const INSTALL_CMD = 'bash scripts/install_runtime.sh';

interface OnboardingProps {
  health: BridgeHealth | 'checking';
  onRecheck: () => void;
  onOpenSettings: () => void;
}

export function Onboarding({ health, onRecheck, onOpenSettings }: OnboardingProps) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-5 overflow-y-auto px-6 py-8 text-center">
      <Logomark className="h-9 w-9 text-signal" />
      <div className="space-y-1.5">
        <p className="text-lg font-semibold tracking-tight text-fg">Let's connect DevScope</p>
        <p className="text-sm leading-[1.55] text-fg-muted">
          DevScope talks to a small bridge running on your machine — your code never leaves it.
        </p>
      </div>

      <SetupGuide />

      <div className="flex items-center gap-2">
        <StatusRow health={health} onRecheck={onRecheck} />
        {health === 'unauthorized' && (
          <button
            onClick={onOpenSettings}
            className="rounded-md bg-signal px-3 py-1.5 text-xs font-medium text-signal-contrast transition-colors duration-fast ease-tool hover:bg-signal-hover"
          >
            Open Settings
          </button>
        )}
      </div>

      {health === 'offline' && <InstallRuntimeHint />}
    </div>
  );
}

function InstallRuntimeHint() {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    void navigator.clipboard.writeText(INSTALL_CMD).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  };
  return (
    <div className="space-y-1.5 text-center">
      <p className="text-xs text-fg-muted">
        Runtime not running? Install it once as a background service (auto-starts, survives reboots) — run from the repo root:
      </p>
      <div className="inline-flex items-center gap-2 rounded-md border border-line bg-surface-raised px-2.5 py-1.5">
        <code className="text-xs text-fg">{INSTALL_CMD}</code>
        <button
          type="button"
          onClick={copy}
          aria-label="Copy install command"
          className="text-fg-muted transition-colors duration-fast ease-tool hover:text-fg"
        >
          {copied ? <Check size={13} className="text-signal" /> : <Copy size={13} />}
        </button>
      </div>
    </div>
  );
}

function StatusRow({ health, onRecheck }: { health: BridgeHealth | 'checking'; onRecheck: () => void }) {
  if (health === 'checking') {
    return (
      <span className="flex items-center gap-1.5 text-xs text-fg-muted">
        <Loader2 size={13} strokeWidth={2} className="animate-spin" />
        Looking for the bridge…
      </span>
    );
  }
  return (
    <div className="flex items-center gap-2">
      <span className="flex items-center gap-1.5 text-xs text-fg-muted">
        <span className="inline-block h-1.5 w-1.5 rounded-full bg-fg-subtle" aria-hidden />
        {health === 'unauthorized' ? 'Waiting for a valid token' : 'Bridge not detected yet'}
      </span>
      <button
        onClick={onRecheck}
        className="rounded-sm px-2 py-0.5 text-2xs font-medium text-signal transition-colors duration-fast ease-tool hover:bg-signal-subtle"
      >
        Check again
      </button>
    </div>
  );
}
