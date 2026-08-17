/**
 * SessionSidebar — left rail with sessions grouped by project, kind, and agent.
 *
 * Structure per project:
 *   Chats -> Claude / Cursor
 *   Tasks & agents -> Claude / Cursor
 */
import React, { useCallback, useMemo, useState } from 'react';
import {
  Bot,
  ChevronRight,
  HelpCircle,
  ListPlus,
  MessageSquare,
  Plus,
  Settings as SettingsIcon,
  TerminalSquare,
  Trash2,
} from 'lucide-react';
import type { Agent } from '@/shared/frames';
import type { SessionState } from '../store/sessionStore';
import { relativeTime } from '../utils/relativeTime';
import { needsUrgentStripAttention, type SessionAttention } from '../utils/sessionAttention';
import { deriveWorkingState } from '../utils/workingState';
import { findPendingPermission } from '../store/sessionStore';
import {
  agentFolderLabel,
  purposeBadge,
  resolveSessionPurpose,
  sessionKindFor,
  type SessionKind,
} from '../utils/sessionKind';
import { groupSessionsForSidebar, type ProjectGroup } from '../utils/sessionSidebarGroups';
import { AgentBadge } from './AgentBadge';
import { Logomark } from './Logomark';

const COLLAPSED_KEY = 'ds-collapsed-sidebar-v2';

interface SessionSidebarProps {
  sessions: SessionState[];
  activeSession: string | null;
  onSelect: (name: string) => void;
  onNewChat: () => void;
  onNewTask: () => void;
  onDelete: (name: string) => void;
  onSettingsClick: () => void;
  onGlossaryClick: () => void;
  onOpenTerminal: (session: string) => void;
  isConnected: boolean;
  attentionBySession?: ReadonlyMap<string, SessionAttention>;
}

function loadCollapsed(): Set<string> {
  try {
    const raw = localStorage.getItem(COLLAPSED_KEY);
    return new Set(raw ? (JSON.parse(raw) as string[]) : []);
  } catch {
    return new Set();
  }
}

function collapseKey(...parts: string[]): string {
  return parts.join('|');
}

export function SessionSidebar({
  sessions,
  activeSession,
  onSelect,
  onNewChat,
  onNewTask,
  onDelete,
  onSettingsClick,
  onGlossaryClick,
  onOpenTerminal,
  isConnected,
  attentionBySession,
}: SessionSidebarProps) {
  const [collapsed, setCollapsed] = useState<Set<string>>(loadCollapsed);
  const groups = useMemo(() => groupSessionsForSidebar(sessions), [sessions]);

  const toggle = useCallback((key: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      try {
        localStorage.setItem(COLLAPSED_KEY, JSON.stringify([...next]));
      } catch {
        /* ignore */
      }
      return next;
    });
  }, []);

  const isCollapsed = useCallback((key: string) => collapsed.has(key), [collapsed]);

  return (
    <aside className="flex h-full w-[196px] flex-shrink-0 flex-col border-r border-line bg-surface-raised">
      <div className="flex items-center justify-between px-3 py-2.5">
        <span className="flex items-center gap-1.5 text-sm font-semibold tracking-tight text-fg">
          <Logomark className="h-4 w-4 text-signal" />
          DevScope
        </span>
        <div className="flex items-center gap-1">
          <button
            onClick={onNewTask}
            aria-label="New task"
            title="New autonomous task"
            className="flex h-7 w-7 items-center justify-center rounded-md text-fg-muted transition-colors duration-fast ease-tool hover:bg-surface-overlay hover:text-signal"
          >
            <ListPlus size={16} strokeWidth={2} />
          </button>
          <button
            onClick={onNewChat}
            aria-label="New chat"
            title="New chat"
            className="flex h-7 w-7 items-center justify-center rounded-md text-fg-muted transition-colors duration-fast ease-tool hover:bg-surface-overlay hover:text-signal"
          >
            <Plus size={16} strokeWidth={2} />
          </button>
        </div>
      </div>

      <div className="mx-3 border-t border-line" />

      <div role="listbox" aria-label="Sessions" className="flex-1 overflow-y-auto px-1.5 py-1.5">
        {groups.length === 0 ? (
          <p className="px-2 py-4 text-center text-xs text-fg-subtle">No sessions yet</p>
        ) : (
          groups.map((group) => (
            <ProjectBlock
              key={group.cwd}
              group={group}
              activeSession={activeSession}
              isCollapsed={isCollapsed}
              onToggle={toggle}
              onSelect={onSelect}
              onDelete={onDelete}
              onOpenTerminal={onOpenTerminal}
              attentionBySession={attentionBySession}
            />
          ))
        )}
      </div>

      <div className="flex items-center justify-between border-t border-line px-3 py-2">
        <ConnectionStatus isConnected={isConnected} />
        <div className="flex items-center gap-0.5">
          <button
            onClick={onGlossaryClick}
            aria-label="Help & glossary"
            title="Help & glossary"
            className="flex h-7 w-7 items-center justify-center rounded-md text-fg-subtle transition-colors duration-fast ease-tool hover:bg-surface-overlay hover:text-fg"
          >
            <HelpCircle size={14} strokeWidth={1.75} />
          </button>
          <button
            onClick={onSettingsClick}
            aria-label="Settings"
            className="flex h-7 w-7 items-center justify-center rounded-md text-fg-subtle transition-colors duration-fast ease-tool hover:bg-surface-overlay hover:text-fg"
          >
            <SettingsIcon size={14} strokeWidth={1.75} />
          </button>
        </div>
      </div>
    </aside>
  );
}

interface ProjectBlockProps {
  group: ProjectGroup;
  activeSession: string | null;
  isCollapsed: (key: string) => boolean;
  onToggle: (key: string) => void;
  onSelect: (name: string) => void;
  onDelete: (name: string) => void;
  onOpenTerminal: (name: string) => void;
  attentionBySession?: ReadonlyMap<string, SessionAttention>;
}

function ProjectBlock({
  group,
  activeSession,
  isCollapsed,
  onToggle,
  onSelect,
  onDelete,
  onOpenTerminal,
  attentionBySession,
}: ProjectBlockProps) {
  const projectKey = collapseKey('project', group.cwd);
  const projectCollapsed = isCollapsed(projectKey);
  const hasActive = group.sections.some((sec) =>
    sec.agents.some((b) => b.sessions.some((s) => s.name === activeSession)),
  );

  return (
    <div className="mb-1">
      <button
        onClick={() => onToggle(projectKey)}
        title={group.label}
        className="group flex w-full items-center gap-1 rounded-md px-1.5 py-1 text-2xs font-semibold uppercase tracking-wider text-fg-subtle transition-colors duration-fast ease-tool hover:bg-surface-overlay/60 hover:text-fg-muted"
      >
        <ChevronRight
          size={11}
          strokeWidth={2.5}
          className={`flex-shrink-0 transition-transform duration-fast ease-tool ${projectCollapsed ? '' : 'rotate-90'}`}
        />
        <span className="truncate normal-case">{group.label}</span>
        {projectCollapsed && hasActive && (
          <span className="h-1.5 w-1.5 flex-shrink-0 rounded-full bg-signal" aria-hidden />
        )}
        <span className="ml-auto flex-shrink-0 tabular-nums text-fg-subtle">
          {group.sections.reduce((n, s) => n + s.sessionCount, 0)}
        </span>
      </button>

      {!projectCollapsed &&
        group.sections.map((section) => (
          <KindBlock
            key={`${group.cwd}-${section.kind}`}
            projectCwd={group.cwd}
            sectionKind={section.kind}
            label={section.label}
            agents={section.agents}
            activeSession={activeSession}
            isCollapsed={isCollapsed}
            onToggle={onToggle}
            onSelect={onSelect}
            onDelete={onDelete}
            onOpenTerminal={onOpenTerminal}
            attentionBySession={attentionBySession}
          />
        ))}
    </div>
  );
}

interface KindBlockProps {
  projectCwd: string;
  sectionKind: SessionKind;
  label: string;
  agents: ProjectGroup['sections'][number]['agents'];
  activeSession: string | null;
  isCollapsed: (key: string) => boolean;
  onToggle: (key: string) => void;
  onSelect: (name: string) => void;
  onDelete: (name: string) => void;
  onOpenTerminal: (name: string) => void;
  attentionBySession?: ReadonlyMap<string, SessionAttention>;
}

function KindBlock({
  projectCwd,
  sectionKind,
  label,
  agents,
  activeSession,
  isCollapsed,
  onToggle,
  onSelect,
  onDelete,
  onOpenTerminal,
  attentionBySession,
}: KindBlockProps) {
  const kindKey = collapseKey('kind', projectCwd, sectionKind);
  const kindCollapsed = isCollapsed(kindKey);
  const isTask = sectionKind === 'task';
  const sessionCount = agents.reduce((n, b) => n + b.sessions.length, 0);
  const hasActive = agents.some((b) => b.sessions.some((s) => s.name === activeSession));

  return (
    <div className={`ml-1 mt-0.5 ${isTask ? 'rounded-md border border-dashed border-line/80 px-0.5 pb-0.5' : ''}`}>
      <button
        onClick={() => onToggle(kindKey)}
        className={`flex w-full items-center gap-1 rounded-md px-1.5 py-0.5 text-2xs font-medium ${
          isTask ? 'text-warning' : 'text-fg-muted'
        } transition-colors hover:bg-surface-overlay/50`}
      >
        <ChevronRight
          size={10}
          strokeWidth={2.5}
          className={`flex-shrink-0 transition-transform ${kindCollapsed ? '' : 'rotate-90'}`}
        />
        {isTask ? <Bot size={11} className="flex-shrink-0" /> : <MessageSquare size={11} className="flex-shrink-0" />}
        <span className="truncate">{label}</span>
        {kindCollapsed && hasActive && (
          <span className="h-1.5 w-1.5 flex-shrink-0 rounded-full bg-signal" aria-hidden />
        )}
        <span className="ml-auto tabular-nums text-fg-subtle">{sessionCount}</span>
      </button>

      {!kindCollapsed &&
        agents.map((bucket) => (
          <AgentBlock
            key={`${projectCwd}-${sectionKind}-${bucket.agent}`}
            projectCwd={projectCwd}
            sectionKind={sectionKind}
            agent={bucket.agent}
            sessions={bucket.sessions}
            activeSession={activeSession}
            isCollapsed={isCollapsed}
            onToggle={onToggle}
            onSelect={onSelect}
            onDelete={onDelete}
            onOpenTerminal={onOpenTerminal}
            attentionBySession={attentionBySession}
          />
        ))}
    </div>
  );
}

interface AgentBlockProps {
  projectCwd: string;
  sectionKind: SessionKind;
  agent: Agent;
  sessions: SessionState[];
  activeSession: string | null;
  isCollapsed: (key: string) => boolean;
  onToggle: (key: string) => void;
  onSelect: (name: string) => void;
  onDelete: (name: string) => void;
  onOpenTerminal: (name: string) => void;
  attentionBySession?: ReadonlyMap<string, SessionAttention>;
}

function AgentBlock({
  projectCwd,
  sectionKind,
  agent,
  sessions,
  activeSession,
  isCollapsed,
  onToggle,
  onSelect,
  onDelete,
  onOpenTerminal,
  attentionBySession,
}: AgentBlockProps) {
  const agentKey = collapseKey('agent', projectCwd, sectionKind, agent);
  const agentCollapsed = isCollapsed(agentKey);
  const hasActive = sessions.some((s) => s.name === activeSession);

  return (
    <div className="ml-2">
      <button
        onClick={() => onToggle(agentKey)}
        className="flex w-full items-center gap-1 rounded px-1 py-0.5 text-2xs text-fg-subtle hover:bg-surface-overlay/40"
      >
        <ChevronRight
          size={9}
          strokeWidth={2.5}
          className={`flex-shrink-0 transition-transform ${agentCollapsed ? '' : 'rotate-90'}`}
        />
        <AgentBadge agent={agent} />
        <span className="truncate">{agentFolderLabel(agent)}</span>
        {agentCollapsed && hasActive && (
          <span className="h-1.5 w-1.5 flex-shrink-0 rounded-full bg-signal" aria-hidden />
        )}
        <span className="ml-auto tabular-nums">{sessions.length}</span>
      </button>

      {!agentCollapsed &&
        sessions.map((session) => (
          <SessionRow
            key={session.name}
            session={session}
            isActive={session.name === activeSession}
            isTask={sessionKindFor(session.name, session.purpose) === 'task'}
            needsAttention={needsUrgentStripAttention(attentionBySession?.get(session.name))}
            onSelect={onSelect}
            onDelete={onDelete}
            onOpenTerminal={onOpenTerminal}
          />
        ))}
    </div>
  );
}

interface SessionRowProps {
  session: SessionState;
  isActive: boolean;
  isTask: boolean;
  needsAttention: boolean;
  onSelect: (name: string) => void;
  onDelete: (name: string) => void;
  onOpenTerminal: (name: string) => void;
}

function SessionRow({
  session,
  isActive,
  isTask,
  needsAttention,
  onSelect,
  onDelete,
  onOpenTerminal,
}: SessionRowProps) {
  const handleDelete = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation();
      onDelete(session.name);
    },
    [session.name, onDelete],
  );

  const handleTerminal = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation();
      onOpenTerminal(session.name);
    },
    [session.name, onOpenTerminal],
  );

  const pending = findPendingPermission(session.messages);
  const working = deriveWorkingState(session, Boolean(pending)).isWorking;
  const badge = purposeBadge(resolveSessionPurpose(session.name, session.purpose));

  return (
    <div
      role="option"
      aria-selected={isActive}
      tabIndex={0}
      onClick={() => onSelect(session.name)}
      onKeyDown={(e) => e.key === 'Enter' && onSelect(session.name)}
      className={`group relative mb-0.5 ml-2 flex cursor-pointer flex-col rounded-md px-2 py-1.5 transition-colors duration-fast ease-tool ${
        needsAttention
          ? 'ring-1 ring-warning/60 bg-warning-subtle/40'
          : isTask
            ? isActive
              ? 'bg-warning-subtle/30'
              : 'hover:bg-warning-subtle/20'
            : isActive
              ? 'bg-surface-overlay'
              : 'hover:bg-surface-overlay/60'
      }`}
    >
      {isActive && (
        <span
          className={`absolute left-0 top-1.5 bottom-1.5 w-[2px] rounded-full ${
            needsAttention ? 'bg-warning animate-cursor-pulse' : isTask ? 'bg-warning/80' : 'bg-signal'
          }`}
          aria-hidden
        />
      )}

      <div className="flex min-w-0 items-center justify-between gap-1">
        <span className="flex min-w-0 items-center gap-1">
          {needsAttention ? (
            <span className="h-1.5 w-1.5 flex-shrink-0 rounded-full bg-warning animate-cursor-pulse" aria-hidden />
          ) : working ? (
            <span className="h-1.5 w-1.5 flex-shrink-0 rounded-full bg-signal animate-cursor-pulse" aria-hidden />
          ) : isTask ? (
            <Bot size={11} className="flex-shrink-0 text-warning/80" aria-hidden />
          ) : (
            <MessageSquare size={11} className="flex-shrink-0 text-fg-subtle" aria-hidden />
          )}
          <span
            className={`truncate text-xs ${isActive ? 'font-semibold text-fg' : 'font-medium text-fg-muted'}`}
            title={session.name}
          >
            {session.name}
          </span>
        </span>
        <div className="flex flex-shrink-0 items-center">
          <button
            onClick={handleTerminal}
            aria-label={`Open terminal for session ${session.name}`}
            title="Open terminal"
            className="rounded p-0.5 text-fg-subtle transition-all duration-fast ease-tool hover:bg-signal-subtle hover:text-signal"
          >
            <TerminalSquare size={12} strokeWidth={2} />
          </button>
          <button
            onClick={handleDelete}
            aria-label={`Delete session ${session.name}`}
            className="rounded p-0.5 text-fg-subtle opacity-0 transition-all duration-fast ease-tool hover:bg-danger-subtle hover:text-danger group-hover:opacity-100"
          >
            <Trash2 size={12} strokeWidth={2} />
          </button>
        </div>
      </div>

      <div className="mt-0.5 flex items-center gap-1.5 pl-3">
        {badge && (
          <span className="rounded bg-warning-subtle/50 px-1 py-px text-[9px] font-medium uppercase tracking-wide text-warning">
            {badge}
          </span>
        )}
        <span className="text-2xs text-fg-subtle">{relativeTime(session.lastUsed)}</span>
      </div>
    </div>
  );
}

function ConnectionStatus({ isConnected }: { isConnected: boolean }) {
  return (
    <span className="flex items-center gap-1.5 text-2xs text-fg-muted">
      <span
        className={`inline-block h-1.5 w-1.5 rounded-full ${isConnected ? 'bg-success' : 'bg-fg-subtle'}`}
        aria-hidden
      />
      {isConnected ? 'connected' : 'offline'}
    </span>
  );
}
