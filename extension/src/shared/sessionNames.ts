/** Orchestrator + manager sessions — always-on bridge WS. */
export function isPersistentAutomationSession(name: string): boolean {
  return name === 'mom' || name.startsWith('mgr-');
}

/** Worker sessions — WS only while a turn is running. */
export function isWorkerSession(name: string): boolean {
  return name.startsWith('worker-');
}

/** Any automation namespace (mom / mgr / worker). */
export function isAutomationSession(name: string): boolean {
  return isPersistentAutomationSession(name) || isWorkerSession(name);
}
