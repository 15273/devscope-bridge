/**
 * sessionControlCommands — bridge-side commands that run in parallel (never queued to Claude stdin).
 */
const SESSION_CONTROL_VERBS = new Set([
  '/medic',
  '/interrupt',
  '/ask',
  '/cursor-ctx',
  '/ctx',
]);

/** True for /medic, /interrupt, /ask, /cursor-ctx — handled by dev_bridge, not the stuck turn. */
export function isSessionControlCommand(text: string): boolean {
  const verb = text.trim().split(/\s+/)[0]?.toLowerCase();
  return verb ? SESSION_CONTROL_VERBS.has(verb) : false;
}

export function sessionControlHint(text: string): string {
  const verb = text.trim().split(/\s+/)[0]?.toLowerCase();
  switch (verb) {
    case '/medic':
      return 'Watchdog Medic — separate diagnostic agent (runs now, not queued)';
    case '/interrupt':
      return 'Stop the current turn on the live session';
    case '/ask':
      return 'Parallel side-query (separate process)';
    case '/cursor-ctx':
    case '/ctx':
      return 'Cursor codebase scout → forwards context to Claude when done';
    default:
      return 'Session command — runs on a parallel path';
  }
}
