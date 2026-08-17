/**
 * AgentBadge — small identity pill for the agent driving a session.
 *
 * Color is never the sole differentiator (a11y): the lowercase label is always
 * present alongside the brand-colored dot.
 */
import type { Agent } from '@/shared/frames';

const LABEL: Record<Agent, string> = {
  claude: 'claude',
  cursor: 'cursor',
};

export function AgentBadge({ agent }: { agent: Agent }) {
  const isCursor = agent === 'cursor';
  return (
    <span className="inline-flex items-center gap-1 font-mono text-2xs leading-none text-fg-muted">
      <span
        className={`inline-block h-1.5 w-1.5 rounded-full ${isCursor ? 'bg-cursor' : 'bg-claude'}`}
        aria-hidden
      />
      {LABEL[agent]}
    </span>
  );
}
