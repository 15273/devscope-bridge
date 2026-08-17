/**
 * bridgeFrameHints.ts — classify special agent_activity labels the bridge
 * reliability overhaul emits (compact lifecycle from Task A7, steering-drop
 * warning from Task A8). Matching is tolerant: labels are human-facing text.
 */

/** A8: "steering message may have been dropped — resend or Stop". */
export function isSteeringDropWarning(label: string): boolean {
  const lower = label.toLowerCase();
  return lower.includes('steering') && lower.includes('dropped');
}

/** A7 compact lifecycle frames → card phase, or null for unrelated activity. */
export function classifyCompactActivity(label: string): 'start' | 'done' | 'failed' | null {
  const lower = label.trim().toLowerCase();
  if (lower.startsWith('compacting session')) return 'start';
  if (/^compact(ion)? (done|complete|completed|succeeded|finished)/.test(lower)) return 'done';
  if (/^compact(ion)? fail/.test(lower)) return 'failed';
  return null;
}
