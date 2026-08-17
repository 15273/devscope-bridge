import type { Agent } from '@/shared/frames';
import type { SessionState } from '../store/sessionStore';
import { sessionKindFor, sessionKindLabel, type SessionKind } from './sessionKind';

export const NO_PROJECT = '^@no-project';

const AGENT_ORDER: Agent[] = ['claude', 'cursor'];

export interface AgentBucket {
  agent: Agent;
  sessions: SessionState[];
}

export interface KindSection {
  kind: SessionKind;
  label: string;
  agents: AgentBucket[];
  sessionCount: number;
}

export interface ProjectGroup {
  cwd: string;
  label: string;
  sections: KindSection[];
  lastUsed: number;
}

function projectLabel(cwd: string): string {
  if (!cwd) return 'ללא פרויקט';
  return cwd.split('/').filter(Boolean).slice(-1)[0] ?? cwd;
}

function sortByLastUsed(sessions: SessionState[]): SessionState[] {
  return [...sessions].sort(
    (a, b) => new Date(b.lastUsed).getTime() - new Date(a.lastUsed).getTime(),
  );
}

function bucketByAgent(sessions: SessionState[]): AgentBucket[] {
  const map = new Map<Agent, SessionState[]>();
  for (const s of sessions) {
    const key = s.agent ?? 'claude';
    const list = map.get(key) ?? [];
    list.push(s);
    map.set(key, list);
  }
  return AGENT_ORDER.filter((agent) => map.has(agent)).map((agent) => ({
    agent,
    sessions: sortByLastUsed(map.get(agent)!),
  }));
}

function buildKindSection(kind: SessionKind, sessions: SessionState[]): KindSection | null {
  if (sessions.length === 0) return null;
  const agents = bucketByAgent(sessions);
  return {
    kind,
    label: sessionKindLabel(kind),
    agents,
    sessionCount: sessions.length,
  };
}

export function groupSessionsForSidebar(sessions: SessionState[]): ProjectGroup[] {
  const byProject = new Map<string, SessionState[]>();
  for (const s of sessions) {
    const key = s.cwd || NO_PROJECT;
    const list = byProject.get(key) ?? [];
    list.push(s);
    byProject.set(key, list);
  }

  const groups: ProjectGroup[] = [];
  for (const [cwdKey, list] of byProject) {
    const chats: SessionState[] = [];
    const tasks: SessionState[] = [];
    for (const s of list) {
      const kind = sessionKindFor(s.name, s.purpose);
      if (kind === 'chat') chats.push(s);
      else tasks.push(s);
    }

    const sections = [
      buildKindSection('chat', chats),
      buildKindSection('task', tasks),
    ].filter((s): s is KindSection => s !== null);

    if (sections.length === 0) continue;

    const sorted = sortByLastUsed(list);
    groups.push({
      cwd: cwdKey,
      label: projectLabel(cwdKey === NO_PROJECT ? '' : cwdKey),
      sections,
      lastUsed: new Date(sorted[0].lastUsed).getTime(),
    });
  }

  return groups.sort((a, b) => b.lastUsed - a.lastUsed);
}
