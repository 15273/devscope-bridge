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
  playbook: SchedulePlaybook;
  instruction?: string | null;
  status: string;
  bootstrapped?: boolean;
}

export async function fetchActiveSetupDraft(): Promise<ScheduleSetupDraft | null> {
  try {
    const token = await getToken();
    const res = await fetch(`${BRIDGE_HTTP}/schedules/setup/active`, {
      headers: authHeaders(token),
    });
    if (!res.ok) return null;
    const body = (await res.json()) as { draft?: ScheduleSetupDraft | null };
    return body.draft ?? null;
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

export async function startScheduleSetup(payload: {
  title: string;
  goal: string;
  entryUrl: string;
  domain?: string;
  agent?: Agent;
  setupMode?: AgentMode;
  instruction?: string;
}): Promise<ScheduleSetupDraft | null> {
  try {
    const token = await getToken();
    const res = await fetch(`${BRIDGE_HTTP}/schedules/setup/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
      body: JSON.stringify({
        title: payload.title,
        goal: payload.goal,
        entry_url: payload.entryUrl,
        domain: payload.domain ?? 'browser',
        agent: payload.agent ?? 'claude',
        setup_mode: payload.setupMode ?? 'inspect',
        instruction: payload.instruction,
      }),
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

export async function completeScheduleSetup(draftId: string): Promise<boolean> {
  try {
    const token = await getToken();
    const res = await fetch(`${BRIDGE_HTTP}/schedules/setup/drafts/${draftId}/complete`, {
      method: 'POST',
      headers: authHeaders(token),
    });
    return res.ok;
  } catch {
    return false;
  }
}
