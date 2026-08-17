/**
 * Schedule discover — Claude + browser MCP playbook draft for new schedules.
 */
import { BRIDGE_HTTP, authHeaders, getToken, type SchedulePlaybook } from '../bridge';

export interface ScheduleDiscoverResult {
  ok: boolean;
  playbook?: SchedulePlaybook;
  instruction?: string | null;
  session?: string | null;
  error?: string;
  raw_preview?: string;
}

export async function discoverSchedulePlaybook(payload: {
  entryUrl: string;
  goal: string;
  session?: string | null;
  domain?: string;
  agent?: 'claude' | 'cursor';
}): Promise<ScheduleDiscoverResult> {
  try {
    const token = await getToken();
    const res = await fetch(`${BRIDGE_HTTP}/schedules/discover`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
      body: JSON.stringify({
        entry_url: payload.entryUrl,
        goal: payload.goal,
        session: payload.session ?? undefined,
        domain: payload.domain ?? 'browser',
        agent: payload.agent ?? 'claude',
      }),
      signal: AbortSignal.timeout(200_000),
    });
    const body = (await res.json()) as {
      ok: boolean;
      data?: ScheduleDiscoverResult;
      error?: string;
    };
    if (!body.ok) {
      return {
        ok: false,
        error: body.error ?? body.data?.error ?? 'discover failed',
        raw_preview: body.data?.raw_preview,
      };
    }
    const data = body.data!;
    return {
      ok: true,
      playbook: data.playbook,
      instruction: data.instruction,
      session: data.session,
    };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}
