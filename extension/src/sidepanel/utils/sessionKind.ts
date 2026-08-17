import type { Agent } from '@/shared/frames';

/** How the session is used — user chat vs orchestrator agent. */
export type SessionPurpose = 'chat' | 'worker' | 'manager' | 'orchestrator' | 'schedule_setup';

export type SessionKind = 'chat' | 'task';

export function resolveSessionPurpose(name: string, purpose?: string | null): SessionPurpose {
  if (
    purpose === 'worker' ||
    purpose === 'manager' ||
    purpose === 'orchestrator' ||
    purpose === 'schedule_setup'
  ) {
    return purpose;
  }
  if (/^sched-setup-/i.test(name)) return 'schedule_setup';
  if (/^worker-/i.test(name)) return 'worker';
  if (/^mgr-/i.test(name)) return 'manager';
  if (name === 'mom') return 'orchestrator';
  return 'chat';
}

export function sessionKindFor(name: string, purpose?: string | null): SessionKind {
  const p = resolveSessionPurpose(name, purpose);
  if (p === 'schedule_setup') return 'chat';
  return p === 'chat' ? 'chat' : 'task';
}

export function sessionKindLabel(kind: SessionKind): string {
  return kind === 'chat' ? "צ'אטים" : 'משימות וסוכנים';
}

export function agentFolderLabel(agent: Agent): string {
  return agent === 'cursor' ? 'Cursor' : 'Claude';
}

export function purposeBadge(purpose: SessionPurpose): string | null {
  switch (purpose) {
    case 'worker':
      return 'worker';
    case 'manager':
      return 'manager';
    case 'orchestrator':
      return 'orchestrator';
    case 'schedule_setup':
      return 'הגדרת תזמון';
    default:
      return null;
  }
}
