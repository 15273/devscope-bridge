/**
 * Schedule setup — dedicated chat session for deep playbook research.
 */
import {
  BRIDGE_HTTP,
  authHeaders,
  getToken,
  type SchedulePlaybook,
} from '../bridge';
import type { Agent, AgentMode } from '@/shared/frames';

export interface ScheduleSetupDraft {
  id: string;
  session_name: string;
  title: string;
  goal: string;
  entry_url: string;
  domain: string;
  agent: Agent;
  setup_mode: AgentMode;
  runtime_mode?: AgentMode;
  recurrence?: Record<string, unknown>;
  autonomy_policy?: string | null;
  playbook: SchedulePlaybook;
  instruction?: string | null;
  status: string;
  schedule_id?: number;
  bootstrapped?: boolean;
}

/** Setup sessions are named sched-setup-{draftId} — derive the draft id back. */
export function draftIdForSession(sessionName: string): string | null {
  const m = /^sched-setup-([0-9a-f]+)$/.exec(sessionName);
  return m ? m[1] : null;
}

/** Start a chat-first setup draft: everything beyond the title fills in by conversation. */
export async function startSetup(title?: string): Promise<ScheduleSetupDraft | null> {
  try {
    const token = await getToken();
    const res = await fetch(`${BRIDGE_HTTP}/schedules/setup/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
      body: JSON.stringify(title ? { title } : {}),
    });
    if (!res.ok) return null;
    const body = (await res.json()) as { draft: ScheduleSetupDraft };
    return body.draft;
  } catch {
    return null;
  }
}

export async function fetchSetupDraft(draftId: string): Promise<ScheduleSetupDraft | null> {
  try {
    const token = await getToken();
    const res = await fetch(`${BRIDGE_HTTP}/schedules/setup/drafts/${draftId}`, {
      headers: authHeaders(token),
    });
    if (!res.ok) return null;
    const body = (await res.json()) as { draft: ScheduleSetupDraft };
    return body.draft;
  } catch {
    return null;
  }
}

export async function bootstrapScheduleSetup(draftId: string): Promise<boolean> {
  try {
    const token = await getToken();
    const res = await fetch(`${BRIDGE_HTTP}/schedules/setup/drafts/${draftId}/bootstrap`, {
      method: 'POST',
      headers: authHeaders(token),
    });
    return res.ok;
  } catch {
    return false;
  }
}

