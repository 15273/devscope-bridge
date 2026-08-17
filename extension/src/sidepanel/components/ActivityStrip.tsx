/**
 * ActivityStrip — compact status while a turn runs (synced to deriveWorkingState).
 *
 * Always shows elapsed time, the current tool, last-output age and queued turns
 * when the bridge provides them (contract 2). A turn with no output for
 * STUCK_AFTER_NO_OUTPUT_MS turns the strip amber with Stop + Medic actions.
 */
import { useEffect, useState } from 'react';
import { ListOrdered, RotateCw, Square, Stethoscope, Wrench } from 'lucide-react';
import { STUCK_AFTER_NO_OUTPUT_MS } from '../utils/workingState';
import { ClaudeSpark } from './ClaudeSpark';

const RESET_HINT_AFTER_MS = 90_000;
/** Show "no output for Ns" only after a meaningful silence. */
const SHOW_NO_OUTPUT_AFTER_MS = 15_000;

interface ActivityStripProps {
  statusLabel: string;
  turnStartedAt?: number;
  isWorking: boolean;
  queuedSteeringCount?: number;
  usageTotal?: { tokens: number; costUsd: number };
  onReset?: () => void;
  onInterrupt?: () => void;
  /** Approval / questions pending — static highlight (no text pulse). */
  needsAttention?: boolean;
  attentionLabel?: string;
  /** Liveness (contract 2) — undefined on bridges without the fields. */
  currentTool?: string | null;
  lastOutputAt?: number | null;
  /** Run the watchdog medic — shown in the stuck state. */
  onMedic?: () => void;
}

function formatElapsed(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

function formatTokens(n: number): string {
  return n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n);
}

export function ActivityStrip({
  statusLabel,
  turnStartedAt,
  isWorking,
  queuedSteeringCount = 0,
  usageTotal,
  onReset,
  onInterrupt,
  needsAttention = false,
  attentionLabel,
  currentTool,
  lastOutputAt,
  onMedic,
}: ActivityStripProps) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!isWorking && !turnStartedAt) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [isWorking, turnStartedAt]);

  const visible = needsAttention || isWorking || Boolean(turnStartedAt) || Boolean(statusLabel);
  const isQueued = queuedSteeringCount > 0;
  const label =
    needsAttention && attentionLabel
      ? attentionLabel
      : statusLabel || (needsAttention ? 'Waiting for you' : 'Working…');
  const hasUsage = usageTotal && usageTotal.tokens > 0;
  const elapsedMs = turnStartedAt ? now - turnStartedAt : 0;
  const longRunning = Boolean(turnStartedAt) && elapsedMs > RESET_HINT_AFTER_MS;
  const stalledQueued = isQueued && longRunning;

  const noOutputMs = isWorking && lastOutputAt != null ? now - lastOutputAt : null;
  const showNoOutput = noOutputMs != null && noOutputMs > SHOW_NO_OUTPUT_AFTER_MS;
  const isStuck =
    !needsAttention && noOutputMs != null && noOutputMs > STUCK_AFTER_NO_OUTPUT_MS;

  return (
    <div
      className={`shrink-0 overflow-hidden border-b transition-[max-height] duration-fast ease-tool ${
        needsAttention || isStuck
          ? 'border-warning/50 bg-warning-subtle'
          : isQueued
            ? 'border-signal/40 bg-signal-subtle'
            : 'border-line bg-surface-raised'
      }`}
      style={{ maxHeight: visible ? (isQueued || isStuck ? 40 : 32) : 0 }}
    >
      <div className={`flex items-center gap-2 px-3 ${isQueued || isStuck ? 'py-2' : 'py-1.5'} text-2xs`}>
        {needsAttention || isStuck ? (
          <span
            className="h-2 w-2 flex-shrink-0 rounded-full bg-warning animate-cursor-pulse"
            aria-hidden
          />
        ) : isQueued ? (
          <ListOrdered size={12} strokeWidth={2} className="flex-shrink-0 text-signal" aria-hidden />
        ) : (
          <ClaudeSpark size={12} />
        )}
        <span
          className={`min-w-0 flex-1 truncate font-mono ${
            isStuck ? 'text-sm text-warning' : isQueued ? 'text-sm text-fg' : 'text-fg-muted'
          }`}
        >
          {isStuck
            ? `No output for ${formatElapsed(noOutputMs!)} — turn may be stuck`
            : stalledQueued
              ? `Turn stuck (${formatElapsed(elapsedMs)}) — queued reply waiting. Stop or Reset`
              : label}
        </span>
        {currentTool && !isStuck && (
          <span
            className="flex flex-shrink-0 items-center gap-1 font-mono text-fg-subtle"
            title="Tool currently running"
          >
            <Wrench size={10} strokeWidth={2} aria-hidden />
            {currentTool}
          </span>
        )}
        {showNoOutput && !isStuck && (
          <span className="flex-shrink-0 font-mono text-fg-subtle" title="Time since last agent output">
            no output {formatElapsed(noOutputMs!)}
          </span>
        )}
        {turnStartedAt && isWorking && (
          <span className="flex-shrink-0 font-mono tabular-nums text-fg-subtle">
            {formatElapsed(now - turnStartedAt)}
          </span>
        )}
        {hasUsage && !isStuck && (
          <span className="flex-shrink-0 font-mono text-fg-subtle">
            {formatTokens(usageTotal!.tokens)}·${usageTotal!.costUsd.toFixed(2)}
          </span>
        )}
        {isStuck && onMedic && (
          <button
            onClick={onMedic}
            title="Run the watchdog medic — diagnoses the stuck session"
            className="flex flex-shrink-0 items-center gap-1 rounded-sm border border-line px-1.5 py-0.5 font-medium text-fg-muted transition-colors duration-fast ease-tool hover:border-signal/40 hover:bg-signal-subtle hover:text-signal"
          >
            <Stethoscope size={10} strokeWidth={2.25} />
            Medic
          </button>
        )}
        {isWorking && onInterrupt && (
          <button
            onClick={onInterrupt}
            title="Stop the current turn"
            className="flex flex-shrink-0 items-center gap-1 rounded-sm border border-line px-1.5 py-0.5 font-medium text-fg-muted transition-colors duration-fast ease-tool hover:border-danger/40 hover:bg-danger-subtle hover:text-danger"
          >
            <Square size={9} strokeWidth={3} className="fill-current" />
            Stop
          </button>
        )}
        {longRunning && onReset && (
          <button
            onClick={onReset}
            title="Taking long? Reset this session (keeps history)"
            className="flex flex-shrink-0 items-center gap-1 rounded-sm border border-line px-1.5 py-0.5 font-medium text-fg-muted transition-colors duration-fast ease-tool hover:border-signal/40 hover:bg-signal-subtle hover:text-signal"
          >
            <RotateCw size={10} strokeWidth={2.25} />
            Reset
          </button>
        )}
      </div>
    </div>
  );
}
