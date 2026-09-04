/**
 * AgentBadge — small identity pill for the agent driving a session.
 *
 * Color is never the sole differentiator (a11y): the lowercase label is always
 * present alongside the brand-colored dot.
 */
import type { Agent } from '@/shared/frames';
import { AGENT_DOT_CLASS, AGENT_LABELS } from '@/shared/agents';

export function AgentBadge({ agent }: { agent: Agent }) {
  return (
    <span className="inline-flex items-center gap-1 font-mono text-2xs leading-none text-fg-muted">
      <span
        className={`inline-block h-1.5 w-1.5 rounded-full ${AGENT_DOT_CLASS[agent]}`}
        aria-hidden
      />
      {AGENT_LABELS[agent].toLowerCase()}
    </span>
  );
}
