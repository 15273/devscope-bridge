/**
 * Format task token/cost usage for Task Board chips.
 */
import type { AgentTask } from '../bridge';

export function taskUsageTokens(task: AgentTask): number {
  if (task.usage_total_tokens != null && task.usage_total_tokens > 0) {
    return task.usage_total_tokens;
  }
  const inp = task.usage_input_tokens ?? 0;
  const out = task.usage_output_tokens ?? 0;
  return inp + out;
}

export function formatUsageTokens(n: number): string {
  if (n <= 0) return '0';
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

export function formatTaskUsageChip(task: AgentTask): string | null {
  const tokens = taskUsageTokens(task);
  if (tokens <= 0) return null;
  const cost =
    task.usage_total_cost_usd != null && task.usage_total_cost_usd > 0
      ? task.usage_total_cost_usd
      : (task.usage_cost_usd ?? 0);
  const tokenPart = formatUsageTokens(tokens);
  if (cost > 0) return `${tokenPart} · $${cost.toFixed(2)}`;
  return tokenPart;
}
