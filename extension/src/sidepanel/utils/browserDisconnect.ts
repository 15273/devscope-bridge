/** Bridge POST /actions 503 — extension WebSocket missing for this session. */
export function isBrowserExtensionDisconnectedError(text: string | undefined | null): boolean {
  if (!text) return false;
  const t = text.toLowerCase();
  return (
    t.includes('browser client not connected') ||
    t.includes('extension not connected') ||
    t.includes('bridge unreachable')
  );
}

export const EXTENSION_DISCONNECTED_BANNER =
  'Extension not connected for this session — open DevScope in this Chrome profile or reconnect';
