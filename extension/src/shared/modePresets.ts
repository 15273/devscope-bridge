/**
 * modePresets.ts — single source of truth for Act / Plan / Inspect / Test copy.
 *
 * Mirrors devscope_bridge/mode_presets.py behavior descriptions for the UI.
 */
import type { AgentMode } from './frames';

export interface ModePresetInfo {
  id: AgentMode;
  label: string;
  /** One-line summary in the mode pill popover */
  summary: string;
  /** When the agent pauses for the user */
  asksWhen: string;
  /** Permission / tool behavior (headless chat) */
  permissions: string;
  /** Default autonomy level */
  autonomy: 'full' | 'plan-first' | 'read-only' | 'test-walk';
}

export const MODE_PRESETS: ModePresetInfo[] = [
  {
    id: 'act',
    label: 'Act',
    summary: 'Runs autonomously — edits files, runs commands, drives the live tab.',
    asksWhen: 'Only via AskUserQuestion (choice cards in chat). No plan gate.',
    permissions: 'Tools run without prompts (bypassPermissions).',
    autonomy: 'full',
  },
  {
    id: 'plan',
    label: 'Plan',
    summary: 'Writes a numbered plan first; waits for your Approve before touching anything.',
    asksWhen: 'Always — plan approval card before execution. Revise by denying and replying.',
    permissions: 'File edits blocked until you approve; ExitPlanMode gate.',
    autonomy: 'plan-first',
  },
  {
    id: 'inspect',
    label: 'Inspect',
    summary: 'Read-only exploration — snapshot, grep, explain. No clicks or file edits.',
    asksWhen: 'Does not ask; reports findings in chat.',
    permissions: 'Read-only tools + browser read APIs only.',
    autonomy: 'read-only',
  },
  {
    id: 'test',
    label: 'Test',
    summary: 'Walks the live app (click, fill, navigate), then writes a structured test report.',
    asksWhen: 'Rarely — same as Act unless stuck on ambiguous UI.',
    permissions: 'Full browser + bash; meant for QA-style flows.',
    autonomy: 'test-walk',
  },
];

export function modePreset(id: AgentMode): ModePresetInfo {
  return MODE_PRESETS.find((m) => m.id === id) ?? MODE_PRESETS[0];
}
