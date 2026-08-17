/**
 * browser_tools_types.ts — Shared types for browser tool results.
 * Kept separate to avoid circular imports between frame_runner and browser_tools.
 */

export interface BrowserToolResult {
  ok: boolean;
  data?: unknown;
  error?: string;
}
