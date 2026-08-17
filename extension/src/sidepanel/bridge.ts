/**
 * bridge.ts — single source of truth for talking to the local dev-bridge.
 *
 * Centralizes the bridge origin, token retrieval and health probing so the
 * auth scheme can be evolved in one place.
 */
export const BRIDGE_HTTP = 'http://127.0.0.1:7878';

/** First-run setup constants (the bridge is distributed as a standalone CLI). */
export const BRIDGE_INSTALL_CMD = 'pipx install devscope-bridge';
export const BRIDGE_TOKEN_PATH = '~/.dev-bridge/token';

const STORAGE_TOKEN_KEY = 'bridgeToken';

/**
 * Every bridge fetch aborts after this timeout: a hung local socket must never
 * freeze a poll loop or leave the UI waiting forever (chat-reliability C2).
 */
export const BRIDGE_FETCH_TIMEOUT_MS = 10_000;
/** Compact runs an LLM summarizer server-side — allow it much longer than a poll. */
const COMPACT_TIMEOUT_MS = 120_000;

/** `fetch` with a hard AbortController timeout. Rejects on timeout like a network error. */
export function bridgeFetch(
  url: string,
  init?: RequestInit,
  timeoutMs: number = BRIDGE_FETCH_TIMEOUT_MS,
): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  return fetch(url, { ...init, signal: controller.signal }).finally(() => clearTimeout(timer));
}

export async function getToken(): Promise<string> {
  const result = await chrome.storage.local.get(STORAGE_TOKEN_KEY);
  return (result[STORAGE_TOKEN_KEY] as string | undefined) ?? '';
}

/**
 * Auth header for bridge HTTP requests.
 *
 * HTTP uses `Authorization: Bearer` (keeps the token out of request URLs/logs).
 * The WebSocket handshake cannot set headers from a browser, so it keeps the
 * token in the query string — that traffic is loopback-only `ws://`.
 */
export function authHeaders(token: string): Record<string, string> {
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/** Open a local file/folder on the user's machine via the bridge. */
export async function openPath(path: string): Promise<boolean> {
  try {
    const token = await getToken();
    const res = await bridgeFetch(`${BRIDGE_HTTP}/open`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
      body: JSON.stringify({ path }),
    });
    return res.ok;
  } catch {
    return false;
  }
}

export interface SlashCommand {
  name: string;
  description: string;
  source: 'project' | 'user' | 'skill' | 'native' | 'builtin';
  /** True for parallel side-query commands like /ask. */
  parallel?: boolean;
  /** Alternate names that resolve to this command (e.g. /cost, /context for /usage). */
  aliases?: string[];
  /**
   * True for commands that are interactive-terminal-only and cannot run in DevScope.
   * The menu shows these greyed-out; selecting one surfaces `note` and does nothing.
   */
  disabled?: boolean;
  /** Short note shown instead of description for disabled commands. */
  note?: string;
  /** True for dev-workflow commands hidden in consumer product mode (Pro shows all). */
  advanced_only?: boolean;
}

/** Fetch custom slash commands the bridge discovered (.claude/commands + skills). */
export async function fetchCommands(): Promise<SlashCommand[]> {
  try {
    const token = await getToken();
    const res = await bridgeFetch(`${BRIDGE_HTTP}/commands`, { headers: authHeaders(token) });
    if (!res.ok) return [];
    const body = (await res.json()) as { commands?: SlashCommand[] };
    return body.commands ?? [];
  } catch {
    return [];
  }
}

/** One official plan limit bucket from /api/oauth/usage. */
export interface UsageLimit {
  utilization: number; // percent used, 0–100
  resets_at?: string;
}

/** Pay-as-you-go usage credits status. */
export interface ExtraUsage {
  is_enabled: boolean;
  utilization?: number | null;
  monthly_limit?: number | null;
  currency?: string | null;
}

/** Active Claude 5-hour usage block (global, shared across all sessions). */
export interface QuotaInfo {
  available: boolean;
  start_time?: string;
  reset_at?: string;
  remaining_minutes?: number;
  total_tokens?: number;
  cost_usd?: number;
  // Official utilization from /api/oauth/usage (keys: five_hour, seven_day, …).
  limits?: Record<string, UsageLimit>;
  extra_usage?: ExtraUsage;
}

export async function fetchQuota(): Promise<QuotaInfo> {
  try {
    const token = await getToken();
    const res = await bridgeFetch(`${BRIDGE_HTTP}/quota`, { headers: authHeaders(token) });
    if (!res.ok) return { available: false };
    return (await res.json()) as QuotaInfo;
  } catch {
    return { available: false };
  }
}

export interface UsageAuditReport {
  active_block: {
    available: boolean;
    total_tokens?: number;
    cost_usd?: number;
    cache_pct_of_total?: number;
    cache_read_tokens?: number;
    entries?: number;
    burn_tokens_per_minute?: number;
    reset_at?: string;
  };
  task_backlog: {
    available: boolean;
    queued?: number;
    in_progress?: number;
    by_source?: Record<string, number>;
    top_task_usage?: Array<{
      id: string;
      title: string;
      tokens: number;
      usage_cost_usd: number;
    }>;
  };
  orchestrator: { paused?: boolean; tick_seconds?: number; max_workers?: number };
  bridge_sessions?: { total_sessions?: number; by_kind?: Record<string, number> };
  top_sessions: Array<{
    bridge_session: string | null;
    total_tokens: number;
    is_orchestrator: boolean;
  }>;
  recommendations: string[];
}

export async function fetchUsageAudit(): Promise<UsageAuditReport | null> {
  try {
    const token = await getToken();
    const res = await bridgeFetch(`${BRIDGE_HTTP}/usage/audit`, { headers: authHeaders(token) });
    if (!res.ok) return null;
    return (await res.json()) as UsageAuditReport;
  } catch {
    return null;
  }
}

export interface CapabilityServer {
  id: string;
  label: string;
  description: string;
  tools_hint: string;
  skill: string;
  ready: boolean;
  status?: Record<string, unknown>;
}

/** One entry of the bridge capability registry (capability_registry.py). */
export interface RegistryCapability {
  id: string;
  label: string;
  description: string;
  backends: string[];
  consumer_visible: boolean;
  available: boolean;
  active_backend: string | null;
  missing: string[];
  mcp_hint: string | null;
  setup_hint: string | null;
}

export interface DevScopeCapabilities {
  mcp_servers: CapabilityServer[];
  skills: { id: string; label: string; path: string }[];
  setup: { mcp_config: string; claude_setup: string; note: string };
  /** Unified capability registry (additive — absent on older bridges). */
  capabilities?: RegistryCapability[];
}

/** MCP + OAuth readiness for Settings → Agent capabilities. */
export async function fetchCapabilities(): Promise<DevScopeCapabilities | null> {
  try {
    const token = await getToken();
    const res = await bridgeFetch(`${BRIDGE_HTTP}/capabilities`, { headers: authHeaders(token) });
    if (!res.ok) return null;
    return (await res.json()) as DevScopeCapabilities;
  } catch {
    return null;
  }
}

/**
 * Interrupt the in-flight agent run for a session (SIGINT to the subprocess).
 * Returns true if the bridge had an active turn to interrupt; false (e.g. 404)
 * means there was nothing running — the caller should clear the UI state itself.
 */
export async function interruptSession(name: string): Promise<boolean> {
  try {
    const token = await getToken();
    const res = await bridgeFetch(`${BRIDGE_HTTP}/sessions/${encodeURIComponent(name)}/interrupt`, {
      method: 'POST',
      headers: authHeaders(token),
    });
    return res.ok;
  } catch {
    return false;
  }
}

/** Kill hung subprocess without deleting session metadata or chat history. */
export async function resetSessionBridge(name: string): Promise<boolean> {
  try {
    const token = await getToken();
    const res = await bridgeFetch(`${BRIDGE_HTTP}/sessions/${encodeURIComponent(name)}/reset`, {
      method: 'POST',
      headers: authHeaders(token),
    });
    return res.ok;
  } catch {
    return false;
  }
}

export interface TranscriptTurn {
  role: 'user' | 'assistant';
  text: string;
}

const CONTEXT_START = '--- PAGE CONTEXT ---';
// A hard-capped preamble loses its END marker and ends with "[context truncated]".
const CONTEXT_ENDS = ['--- END CONTEXT ---', '[context truncated]'];
const RECOVERY_START = '[Bridge context recovery]';
const RECOVERY_SEP = '\n\n---\n\n';

/** Show only what the user typed — composed prompts carry bridge-injected prefixes. */
function stripContextPreamble(text: string): string {
  let out = text;
  if (out.startsWith(RECOVERY_START)) {
    const sep = out.indexOf(RECOVERY_SEP);
    if (sep !== -1) out = out.slice(sep + RECOVERY_SEP.length).trimStart();
  }
  if (!out.startsWith(CONTEXT_START)) return out;
  for (const end of CONTEXT_ENDS) {
    const idx = out.indexOf(end);
    if (idx !== -1) return out.slice(idx + end.length).trimStart();
  }
  return out;
}

/**
 * The CLI transcript stores one assistant entry per message EVENT — a turn with
 * tool calls yields several. The panel renders one bubble per turn, so coalesce
 * consecutive assistant entries; otherwise count-based transcript merges append
 * the "extra" entries as new bubbles and the answer shows up twice.
 */
export function normalizeTranscriptTurns(turns: TranscriptTurn[]): TranscriptTurn[] {
  const out: TranscriptTurn[] = [];
  for (const turn of turns) {
    const text = turn.role === 'user' ? stripContextPreamble(turn.text) : turn.text;
    if (!text.trim()) continue;
    const prev = out[out.length - 1];
    if (prev && prev.role === 'assistant' && turn.role === 'assistant') {
      prev.text = `${prev.text}\n\n${text}`;
    } else {
      out.push({ role: turn.role, text });
    }
  }
  return out;
}

export interface TranscriptResult {
  /** False when the bridge could not be reached / errored — NOT the same as an empty transcript. */
  ok: boolean;
  turns: TranscriptTurn[];
}

/**
 * Fetch the shared conversation transcript for a session.
 * Returns the newest ~300 turns, tool-only entries already filtered server-side,
 * normalized to panel granularity (context preambles stripped from user turns,
 * per-event assistant entries coalesced into one turn each).
 * `ok: false` distinguishes bridge failure from a genuinely empty transcript —
 * callers must surface failures (connection banner), never treat them as "no news".
 */
export async function fetchTranscript(name: string): Promise<TranscriptResult> {
  try {
    const token = await getToken();
    const url = `${BRIDGE_HTTP}/sessions/${encodeURIComponent(name)}/transcript`;
    const res = await bridgeFetch(url, { headers: authHeaders(token) });
    if (!res.ok) return { ok: false, turns: [] };
    const body = (await res.json()) as { turns?: TranscriptTurn[] };
    return { ok: true, turns: normalizeTranscriptTurns(body.turns ?? []) };
  } catch {
    return { ok: false, turns: [] };
  }
}

/**
 * Fetch unresolved interactive requests for a session (chat-reliability
 * contract 3) so pending approval/question cards survive panel close/reopen.
 * Bridges that predate the endpoint 404 — treated as "nothing pending".
 */
export async function fetchPendingRequests(
  name: string,
): Promise<import('@/shared/frames').PermissionRequest[]> {
  try {
    const token = await getToken();
    const url = `${BRIDGE_HTTP}/sessions/${encodeURIComponent(name)}/pending`;
    const res = await bridgeFetch(url, { headers: authHeaders(token) });
    if (!res.ok) return [];
    const body = (await res.json()) as { pending?: import('@/shared/frames').PermissionRequest[] };
    return body.pending ?? [];
  } catch {
    return [];
  }
}

/** Backfill bridge transcript from UI messages (Cursor — no Claude JSONL). */
export async function syncBridgeHistory(
  name: string,
  turns: TranscriptTurn[],
): Promise<void> {
  if (turns.length === 0) return;
  try {
    const token = await getToken();
    await bridgeFetch(`${BRIDGE_HTTP}/sessions/${encodeURIComponent(name)}/history/sync`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
      body: JSON.stringify({ turns }),
    });
  } catch {
    /* non-fatal */
  }
}

export type BridgeHealth = 'connected' | 'unauthorized' | 'offline';

/** Probe the bridge using the stored token; distinguishes bad-token from down. */
export async function pingBridge(): Promise<BridgeHealth> {
  try {
    const token = await getToken();
    const res = await bridgeFetch(`${BRIDGE_HTTP}/sessions`, { headers: authHeaders(token) });
    if (res.ok) return 'connected';
    if (res.status === 401 || res.status === 403) return 'unauthorized';
    return 'offline';
  } catch {
    return 'offline';
  }
}

export type TaskAutonomy = 'guarded' | 'e2e';

export interface CreateTaskPayload {
  title: string;
  instruction?: string;
  detail?: string;
  domain?: string;
  autonomy?: TaskAutonomy;
  /** Project directory workers run in (inherited by the whole subtree). */
  project_path?: string;
}

export interface ClaudeAgentDef {
  name: string;
  description: string;
  model?: string | null;
  source?: string;
}

/** List Claude Code subagents from .claude/agents/*.md */
export async function fetchClaudeAgents(): Promise<ClaudeAgentDef[]> {
  const token = await getToken();
  const res = await bridgeFetch(`${BRIDGE_HTTP}/claude-agents`, { headers: authHeaders(token) });
  if (!res.ok) throw new Error(`fetch agents failed: ${res.status}`);
  const data = (await res.json()) as { agents: ClaudeAgentDef[] };
  return data.agents ?? [];
}

/** Set (or clear) the Claude subagent for a session without sending a chat message. */
export async function setSessionClaudeAgent(
  sessionName: string,
  claudeAgent: string | null,
): Promise<{ ok: boolean; claude_agent: string | null }> {
  const token = await getToken();
  const res = await bridgeFetch(`${BRIDGE_HTTP}/sessions/${encodeURIComponent(sessionName)}/claude-agent`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
    body: JSON.stringify({ claude_agent: claudeAgent }),
  });
  if (!res.ok) throw new Error(`set claude-agent failed: ${res.status}`);
  return res.json() as Promise<{ ok: boolean; claude_agent: string | null }>;
}

/** Summarize session transcript; preamble is injected on the next user message. */
/** Set (or clear) the Claude model for a session without sending a chat message. */
export async function setSessionModel(
  sessionName: string,
  model: string | null,
): Promise<{ ok: boolean; model: string | null }> {
  const token = await getToken();
  const res = await bridgeFetch(`${BRIDGE_HTTP}/sessions/${encodeURIComponent(sessionName)}/model`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
    body: JSON.stringify({ model }),
  });
  if (!res.ok) throw new Error(`set model failed: ${res.status}`);
  return res.json() as Promise<{ ok: boolean; model: string | null }>;
}

export async function requestSessionCompact(
  sessionName: string,
  extra = '',
): Promise<{ ok: boolean; was_real_summary: boolean }> {
  const token = await getToken();
  const res = await bridgeFetch(
    `${BRIDGE_HTTP}/sessions/${encodeURIComponent(sessionName)}/compact`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
      body: JSON.stringify({ extra }),
    },
    COMPACT_TIMEOUT_MS,
  );
  if (!res.ok) throw new Error(`compact failed: ${res.status}`);
  return res.json() as Promise<{ ok: boolean; was_real_summary: boolean }>;
}

/** POST a top-level autonomous task to the orchestrator. */
export async function createTask(payload: CreateTaskPayload): Promise<{ id: string }> {
  const token = await getToken();
  const res = await bridgeFetch(`${BRIDGE_HTTP}/tasks`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
    body: JSON.stringify({
      kind: 'mom_task',
      source: 'extension',
      autonomy: 'guarded',
      ...payload,
    }),
  });
  if (!res.ok) throw new Error(`createTask failed: ${res.status}`);
  return res.json();
}

export interface OrchestratorConfig {
  tick_seconds: number;
  max_workers: number;
  quota_throttle_enabled: boolean;
  quota_high_utilization: number;
  quota_mid_utilization: number;
  paused: boolean;
}

export interface OrchestratorThrottle {
  base_max_workers: number;
  effective_max_workers: number;
  quota_throttle_enabled: boolean;
  utilization: number | null;
  reason: string;
}

export interface AgentTask {
  id: string;
  title: string;
  status: string;
  kind: string;
  domain: string | null;
  instruction: string | null;
  result_summary: string | null;
  detail: string | null;
  parent_id: string | null;
  assignee_session: string | null;
  updated_at: string;
  created_at: string;
  autonomy?: string;
  source?: string | null;
  project_path?: string | null;
  /** Subtree progress, present on top-level project tasks only. */
  progress?: { total: number; done: number; failed: number; pct: number };
  usage_input_tokens?: number;
  usage_output_tokens?: number;
  usage_cache_read_tokens?: number;
  usage_cache_write_tokens?: number;
  usage_cost_usd?: number;
  usage_turn_count?: number;
  /** Own + child worker units (server-computed). */
  usage_total_tokens?: number;
  usage_total_cost_usd?: number;
}

export interface TaskLogEntry {
  id: number;
  task_id: string;
  ts: string;
  actor: string | null;
  message: string;
}

export interface TaskDetail {
  task: AgentTask;
  logs: TaskLogEntry[];
}

export interface PendingApproval {
  id: number;
  task_id: string;
  action: string;
  status: string;
  title: string;
  task_status?: string | null;
  created_at?: string;
  payload?: Record<string, unknown>;
}

export interface TaskBoardSnapshot {
  config: OrchestratorConfig;
  runtime: {
    effective_max_workers: number;
    paused?: boolean;
    running_workers: number;
    queued_ready: number;
    throttle: OrchestratorThrottle;
    last_tick_at?: string | null;
    next_tick_at?: string | null;
    completed_24h?: number;
    usage_24h?: {
      total_tokens: number;
      total_cost_usd: number;
      tasks_with_usage: number;
      hours: number;
    };
  };
  mom?: {
    report?: string | null;
    report_at?: string | null;
  };
  counts: Record<string, number>;
  tasks: AgentTask[];
  pending_approvals: PendingApproval[];
  schedules?: ScheduleEntry[];
}

export interface SchedulePlaybook {
  version?: number;
  site?: string;
  entry_urls?: string[];
  workflow?: string[];
  selectors?: Record<string, string | string[]>;
  fields?: Record<string, string>;
  notes?: string;
  checklist?: string[];
  last_success_at?: string | null;
  learned_from_runs?: number;
}

export interface ScheduleTemplate {
  title?: string;
  kind?: string;
  detail?: string | null;
  domain?: string | null;
  instruction?: string | null;
  autonomy?: string | null;
  agent?: 'claude' | 'cursor';
  mode?: 'act' | 'plan' | 'inspect' | 'test';
  recurrence?: { every_minutes?: number; daily_at?: string };
}

export interface ScheduleEntry {
  id: number;
  title: string;
  template: ScheduleTemplate;
  playbook?: SchedulePlaybook | string | null;
  cron_expr?: string | null;
  next_run_at?: string | null;
  last_run_at?: string | null;
  last_task_id?: string | null;
  enabled?: number | boolean;
  updated_at?: string | null;
}

/** Autonomous Employee configuration (bridge ~/.dev-bridge/employee_config.json). */
export interface EmployeeConfig {
  employee_enabled: boolean;
  board_provider: string;
  board_database: string;
  board_sync_enabled: boolean;
  board_sync_every_ticks: number;
  board_push_max_per_sync: number;
  channels: Record<string, boolean>;
  wa_chat_id: string;
  digest_email: string;
  digest_daily_at: string;
}

export async function fetchEmployeeConfig(): Promise<EmployeeConfig | null> {
  try {
    const token = await getToken();
    const res = await bridgeFetch(`${BRIDGE_HTTP}/employee/config`, { headers: authHeaders(token) });
    if (!res.ok) return null;
    return (await res.json()) as EmployeeConfig;
  } catch {
    return null;
  }
}

export async function patchEmployeeConfig(
  patch: Partial<EmployeeConfig>,
): Promise<EmployeeConfig | null> {
  try {
    const token = await getToken();
    const res = await bridgeFetch(`${BRIDGE_HTTP}/employee/config`, {
      method: 'PATCH',
      headers: { ...authHeaders(token), 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    });
    if (!res.ok) return null;
    return (await res.json()) as EmployeeConfig;
  } catch {
    return null;
  }
}

export async function testEmployeeChannel(channel: string): Promise<boolean> {
  try {
    const token = await getToken();
    const res = await bridgeFetch(`${BRIDGE_HTTP}/employee/test-channel`, {
      method: 'POST',
      headers: { ...authHeaders(token), 'Content-Type': 'application/json' },
      body: JSON.stringify({ channel }),
    });
    return res.ok;
  } catch {
    return false;
  }
}

/** One entry of the plugin-store catalog (featured or live MCP-registry result). */
export interface StoreCatalogItem {
  id: string;
  title: string;
  description: string;
  url: string;
  source: 'featured' | 'registry';
}

/** One plugin installed in .cursor/mcp.json, with live cursor-agent status. */
export interface InstalledPlugin {
  id: string;
  url: string | null;
  description: string;
  status: string;
  ready: boolean;
  needs_login: boolean;
}

/** One directory listing for the in-panel folder picker. */
export interface DirListing {
  ok: boolean;
  path?: string;
  parent?: string | null;
  dirs?: { name: string; path: string }[];
  error?: string;
}

/** List subdirectories via the bridge (empty path = home directory). */
export async function listDirs(path: string): Promise<DirListing> {
  try {
    const token = await getToken();
    const res = await bridgeFetch(
      `${BRIDGE_HTTP}/fs/list-dirs?path=${encodeURIComponent(path)}`,
      { headers: authHeaders(token) },
    );
    if (!res.ok) return { ok: false, error: `HTTP ${res.status}` };
    return (await res.json()) as DirListing;
  } catch {
    return { ok: false, error: 'bridge unreachable' };
  }
}

export async function fetchStoreCatalog(q: string): Promise<StoreCatalogItem[]> {
  try {
    const token = await getToken();
    const res = await bridgeFetch(
      `${BRIDGE_HTTP}/store/catalog?q=${encodeURIComponent(q)}`,
      { headers: authHeaders(token) },
    );
    if (!res.ok) return [];
    const body = (await res.json()) as { items?: StoreCatalogItem[] };
    return body.items ?? [];
  } catch {
    return [];
  }
}

export async function fetchStoreState(): Promise<InstalledPlugin[]> {
  try {
    const token = await getToken();
    const res = await bridgeFetch(`${BRIDGE_HTTP}/store/state`, { headers: authHeaders(token) });
    if (!res.ok) return [];
    const body = (await res.json()) as { plugins?: InstalledPlugin[] };
    return body.plugins ?? [];
  } catch {
    return [];
  }
}

export async function installStorePlugin(
  item: StoreCatalogItem,
): Promise<{ ok: boolean; needs_login?: boolean; error?: string }> {
  try {
    const token = await getToken();
    const res = await bridgeFetch(`${BRIDGE_HTTP}/store/install`, {
      method: 'POST',
      headers: { ...authHeaders(token), 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: item.id, title: item.title, url: item.url }),
    });
    return (await res.json()) as { ok: boolean; needs_login?: boolean; error?: string };
  } catch {
    return { ok: false, error: 'bridge unreachable' };
  }
}

export async function loginStorePlugin(id: string): Promise<boolean> {
  try {
    const token = await getToken();
    const res = await bridgeFetch(`${BRIDGE_HTTP}/store/login`, {
      method: 'POST',
      headers: { ...authHeaders(token), 'Content-Type': 'application/json' },
      body: JSON.stringify({ id }),
    });
    if (!res.ok) return false;
    const body = (await res.json()) as { ok?: boolean };
    return body.ok === true;
  } catch {
    return false;
  }
}

export async function fetchTaskBoard(domain?: string | null): Promise<TaskBoardSnapshot | null> {
  try {
    const token = await getToken();
    const qs = domain ? `?domain=${encodeURIComponent(domain)}` : '';
    const res = await bridgeFetch(`${BRIDGE_HTTP}/orchestrator/board${qs}`, { headers: authHeaders(token) });
    if (!res.ok) return null;
    return (await res.json()) as TaskBoardSnapshot;
  } catch {
    return null;
  }
}

export async function fetchTaskDetail(taskId: string): Promise<TaskDetail | null> {
  try {
    const token = await getToken();
    const res = await bridgeFetch(`${BRIDGE_HTTP}/tasks/${encodeURIComponent(taskId)}`, {
      headers: authHeaders(token),
    });
    if (!res.ok) return null;
    return (await res.json()) as TaskDetail;
  } catch {
    return null;
  }
}

/** Worker session name for a task (assignee or default pattern). */
export function workerSessionForTask(task: Pick<AgentTask, 'id' | 'assignee_session'>): string {
  return task.assignee_session?.trim() || `worker-${task.id}`;
}

export async function fetchOrchestratorConfig(): Promise<{
  config: OrchestratorConfig;
  runtime: { effective_max_workers: number; throttle: OrchestratorThrottle };
} | null> {
  try {
    const token = await getToken();
    const res = await bridgeFetch(`${BRIDGE_HTTP}/orchestrator/config`, { headers: authHeaders(token) });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

export async function patchOrchestratorConfig(
  patch: Partial<OrchestratorConfig>,
): Promise<{ config: OrchestratorConfig; runtime: { effective_max_workers: number; throttle: OrchestratorThrottle } } | null> {
  try {
    const token = await getToken();
    const res = await bridgeFetch(`${BRIDGE_HTTP}/orchestrator/config`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
      body: JSON.stringify(patch),
    });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

export async function cancelTask(taskId: string): Promise<boolean> {
  try {
    const token = await getToken();
    const res = await bridgeFetch(`${BRIDGE_HTTP}/tasks/${encodeURIComponent(taskId)}/cancel`, {
      method: 'POST',
      headers: authHeaders(token),
    });
    return res.ok;
  } catch {
    return false;
  }
}

export async function approveTask(taskId: string): Promise<boolean> {
  try {
    const token = await getToken();
    const res = await bridgeFetch(`${BRIDGE_HTTP}/tasks/${encodeURIComponent(taskId)}/approve`, {
      method: 'POST',
      headers: authHeaders(token),
    });
    return res.ok;
  } catch {
    return false;
  }
}

/** Answer a pending action='question' approval — requeues the task with the answer. */
export async function answerTask(taskId: string, answer: string): Promise<boolean> {
  try {
    const token = await getToken();
    const res = await bridgeFetch(`${BRIDGE_HTTP}/tasks/${encodeURIComponent(taskId)}/answer`, {
      method: 'POST',
      headers: { ...authHeaders(token), 'Content-Type': 'application/json' },
      body: JSON.stringify({ answer }),
    });
    return res.ok;
  } catch {
    return false;
  }
}

export async function rejectTask(taskId: string): Promise<boolean> {
  try {
    const token = await getToken();
    const res = await bridgeFetch(`${BRIDGE_HTTP}/tasks/${encodeURIComponent(taskId)}/reject`, {
      method: 'POST',
      headers: authHeaders(token),
    });
    return res.ok;
  } catch {
    return false;
  }
}

export async function fetchSchedules(): Promise<ScheduleEntry[]> {
  try {
    const token = await getToken();
    const res = await bridgeFetch(`${BRIDGE_HTTP}/schedules`, { headers: authHeaders(token) });
    if (!res.ok) return [];
    const data = (await res.json()) as { schedules: ScheduleEntry[] };
    return data.schedules ?? [];
  } catch {
    return [];
  }
}

export async function createSchedule(payload: {
  title: string;
  template: ScheduleTemplate;
  playbook?: SchedulePlaybook;
  next_run_at?: string;
  enabled?: boolean;
}): Promise<ScheduleEntry | null> {
  try {
    const token = await getToken();
    const res = await bridgeFetch(`${BRIDGE_HTTP}/schedules`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
      body: JSON.stringify(payload),
    });
    if (!res.ok) return null;
    return (await res.json()) as ScheduleEntry;
  } catch {
    return null;
  }
}

export async function patchSchedule(
  scheduleId: number,
  patch: Partial<{
    title: string;
    template: ScheduleTemplate;
    playbook: SchedulePlaybook;
    next_run_at: string;
    enabled: boolean;
  }>,
): Promise<ScheduleEntry | null> {
  try {
    const token = await getToken();
    const res = await bridgeFetch(`${BRIDGE_HTTP}/schedules/${scheduleId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
      body: JSON.stringify(patch),
    });
    if (!res.ok) return null;
    return (await res.json()) as ScheduleEntry;
  } catch {
    return null;
  }
}

export async function patchSchedulePlaybook(
  scheduleId: number,
  patch: Partial<SchedulePlaybook>,
): Promise<SchedulePlaybook | null> {
  try {
    const token = await getToken();
    const res = await bridgeFetch(`${BRIDGE_HTTP}/schedules/${scheduleId}/playbook`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
      body: JSON.stringify({ patch }),
    });
    if (!res.ok) return null;
    const data = (await res.json()) as { playbook: SchedulePlaybook };
    return data.playbook;
  } catch {
    return null;
  }
}

export async function deleteSchedule(scheduleId: number): Promise<boolean> {
  try {
    const token = await getToken();
    const res = await bridgeFetch(`${BRIDGE_HTTP}/schedules/${scheduleId}`, {
      method: 'DELETE',
      headers: authHeaders(token),
    });
    return res.ok;
  } catch {
    return false;
  }
}

/** Normalize playbook from API (string JSON or object). */
export function parseSchedulePlaybook(raw: SchedulePlaybook | string | null | undefined): SchedulePlaybook {
  if (!raw) return {};
  if (typeof raw === 'string') {
    try {
      return JSON.parse(raw) as SchedulePlaybook;
    } catch {
      return {};
    }
  }
  return raw;
}
