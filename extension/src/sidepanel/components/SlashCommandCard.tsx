/**
 * SlashCommandCard — native panel card for bridge-side builtin slash commands.
 *
 * Rendered for role === 'slash_cmd' messages.  Each kind has a distinct header
 * colour and icon so the user can tell usage reports from model switches at a glance.
 *
 * Layout:
 *  ┌─ border-left accent ────────────────────────────────┐
 *  │  <icon> <title>  [kind badge]                       │
 *  │  <pre-formatted body text>                          │
 *  └─────────────────────────────────────────────────────┘
 */
import { Cpu, Database, FileText, FolderPlus, Info, RefreshCw, Zap } from 'lucide-react';
import { claudeModelPreset } from '@/shared/claudeModels';
import type { ChatMessage } from '../store/sessionStore';

interface SlashCommandCardProps {
  message: ChatMessage;
}

type CardKind = 'usage' | 'model' | 'memory' | 'new' | 'compact' | 'status' | 'add_dir';

const KIND_ICON: Record<CardKind, typeof Zap> = {
  usage: Database,
  model: Cpu,
  memory: FileText,
  new: RefreshCw,
  compact: Zap,
  status: Info,
  add_dir: FolderPlus,
};

const KIND_LABEL: Record<CardKind, string> = {
  usage: 'usage',
  model: 'model',
  memory: 'memory',
  new: 'new session',
  compact: 'compact',
  status: 'status',
  add_dir: 'add-dir',
};

function kindAccent(kind: CardKind): string {
  switch (kind) {
    case 'usage':    return 'border-l-signal';
    case 'model':    return 'border-l-success';
    case 'memory':   return 'border-l-fg-subtle';
    case 'new':      return 'border-l-warning';
    case 'compact':  return 'border-l-signal';
    case 'status':   return 'border-l-fg-subtle';
    case 'add_dir':  return 'border-l-success';
  }
}

function KindBadge({ kind }: { kind: CardKind }) {
  const baseClass = 'rounded-sm px-1.5 py-0.5 text-[10px] font-medium';
  switch (kind) {
    case 'usage':
      return <span className={`${baseClass} bg-signal-subtle text-signal`}>{KIND_LABEL[kind]}</span>;
    case 'model':
      return <span className={`${baseClass} bg-success-subtle text-success`}>{KIND_LABEL[kind]}</span>;
    case 'memory':
      return <span className={`${baseClass} bg-surface-overlay text-fg-muted`}>{KIND_LABEL[kind]}</span>;
    case 'new':
      return <span className={`${baseClass} bg-warning-subtle text-warning`}>{KIND_LABEL[kind]}</span>;
    case 'compact':
      return <span className={`${baseClass} bg-signal-subtle text-signal`}>{KIND_LABEL[kind]}</span>;
    case 'status':
      return <span className={`${baseClass} bg-surface-overlay text-fg-muted`}>{KIND_LABEL[kind]}</span>;
    case 'add_dir':
      return <span className={`${baseClass} bg-success-subtle text-success`}>{KIND_LABEL[kind]}</span>;
  }
}

function formatModelCardBody(message: ChatMessage): string {
  const raw = message.text ?? '';
  if (message.slashKind !== 'model') return raw;
  const modelId = message.slashData?.model as string | null | undefined;
  const label = claudeModelPreset(modelId ?? null).label;
  const idLine = modelId ? `${label} (${modelId})` : label;
  return raw.replace(/Active model:\s*None/i, `Active model: ${idLine}`);
}

export function SlashCommandCard({ message }: SlashCommandCardProps) {
  const kind = (message.slashKind ?? 'usage') as CardKind;
  const Icon = KIND_ICON[kind] ?? Database;
  const body = formatModelCardBody(message);

  return (
    <div
      className={`my-1 rounded-md border border-line border-l-2 ${kindAccent(kind)} bg-surface-raised px-3 py-2.5`}
    >
      <div className="mb-1.5 flex items-center gap-2">
        <Icon size={13} strokeWidth={2} className="flex-shrink-0 text-fg-muted" aria-hidden />
        <span className="text-xs font-semibold text-fg">{message.slashTitle ?? message.text}</span>
        <KindBadge kind={kind} />
      </div>
      {body && (
        <pre className="whitespace-pre-wrap font-mono text-2xs leading-relaxed text-fg-muted">
          {body}
        </pre>
      )}
    </div>
  );
}
