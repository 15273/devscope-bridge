/**
 * App — root component for the DevScope side panel (Graphite).
 *
 * Layout:
 *  ┌──────────────┬─────────────────────────────┐
 *  │ SessionSide  │  Chat area / Settings        │
 *  │  bar (176px) │  (flex-1)                    │
 *  └──────────────┴─────────────────────────────┘
 *
 * Global keyboard shortcuts:
 *  Cmd/Ctrl+K → open new session modal
 *  Cmd/Ctrl+1..9 → switch to session by sidebar order
 *  Esc → close modal (handled inside modal)
 */
import { useState, useEffect, useCallback } from 'react';
import { Camera, MessageSquareCode, MousePointerClick, RotateCw } from 'lucide-react';
import { SessionSidebar } from './components/SessionSidebar';
import { Chat } from './components/Chat';
import { Composer } from './components/Composer';
import { Settings } from './components/Settings';
import { Glossary } from './components/Glossary';
import { NewSessionModal } from './components/NewSessionModal';
import { NewTaskModal } from './components/NewTaskModal';
import { Onboarding } from './components/Onboarding';
import { ActivityStrip } from './components/ActivityStrip';
import { StreamDebugPanel } from './components/StreamDebugPanel';
import { BrowserContextStrip } from './components/BrowserContextStrip';
import { CapabilitiesStrip } from './components/CapabilitiesStrip';
import { Logomark } from './components/Logomark';
import { TerminalView } from './components/TerminalView';
import { TerminalSessionView } from './components/TerminalSessionView';
import { useSessionManager } from './hooks/useSessionManager';
import { useBridgeHealth } from './hooks/useBridgeHealth';
import { useUiPrefs } from './hooks/useUiPrefs';
import { chatTerminalId, usePtySession } from './hooks/usePtySession';
import { isAutomationSession } from '@/shared/sessionNames';
import { useRecording } from './hooks/useRecording';
import { useAttentionAlerts } from './hooks/useAttentionAlerts';
import { needsUrgentStripAttention } from './utils/sessionAttention';
import { loadAttentionPrefs, type AttentionPrefs } from './utils/storage';
import { setStreamDebugEnabled } from './utils/streamDebug';
import { findPendingPermission } from './store/sessionStore';
import { deriveWorkingState, shouldWarnCompact } from './utils/workingState';
import { DecisionPanel } from './components/DecisionPanel';
import { TabPickBanner } from './components/TabPickBanner';
import { SessionCoachBanner } from './components/SessionCoachBanner';
import { CompactBanner } from './components/CompactBanner';
import { TokenBattery } from './components/TokenBattery';
import { GlobalBattery } from './components/GlobalBattery';
import { ViewNav } from './components/ViewNav';
import { requestSessionCompact, setSessionModel } from './bridge';
import { WhatsAppCockpit } from './components/cockpit/WhatsAppCockpit';
import { EmailCockpit } from './components/cockpit/EmailCockpit';
import { CalendarCockpit } from './components/cockpit/CalendarCockpit';
import { MetaAdsCockpit } from './components/cockpit/MetaAdsCockpit';
import { useQuota } from './hooks/useQuota';
import { useBrowserStatus } from './hooks/useBrowserStatus';
import { useTaskBoard } from './hooks/useTaskBoard';
import { TaskBoard } from './components/TaskBoard';
import type { QuotaInfo } from './bridge';
import type { Agent } from '@/shared/frames';

interface OpenTerminal {
  terminalId: string;
  session: string;
}

export function App() {
  const {
    state,
    dispatch,
    switchSession: switchSessionBase,
    reconnectSession,
    sendMessage,
    sendMessageViaPty,
    retryMessage,
    cancelSteering,
    createSession,
    deleteSession,
    interrupt,
    resetSession,
    respondPermission,
    syncTranscript,
    mergeTranscript,
    bindSessionTab,
    clearTabPick,
    setBoundTabState,
    setTerminalModeSession,
    compactSession,
    dismissCompactBanner,
  } = useSessionManager();
  const { health, recheck } = useBridgeHealth();
  const uiPrefs = useUiPrefs();

  useEffect(() => {
    setStreamDebugEnabled(uiPrefs.streamDebug);
  }, [uiPrefs.streamDebug]);
  const recordingState = useRecording();
  const [showSettings, setShowSettings] = useState(false);
  const [showGlossary, setShowGlossary] = useState(false);
  const [showNewModal, setShowNewModal] = useState(false);
  const [showNewTaskModal, setShowNewTaskModal] = useState(false);
  const [taskDomainFilter, setTaskDomainFilter] = useState<string | null>(null);
  const [openTerminal, setOpenTerminal] = useState<OpenTerminal | null>(null);
  const [recNow, setRecNow] = useState(0);
  const [attentionPrefs, setAttentionPrefs] = useState<AttentionPrefs>({
    enabled: true,
    sound: true,
    flashTitle: true,
    desktopNotification: true,
    alertWhenActive: false,
  });

  useEffect(() => {
    loadAttentionPrefs().then(setAttentionPrefs).catch(() => {});
    const onStorage = (
      changes: Record<string, chrome.storage.StorageChange>,
      area: string,
    ) => {
      if (area !== 'local' || !changes.attentionPrefs) return;
      const next = changes.attentionPrefs.newValue as AttentionPrefs | undefined;
      if (next) setAttentionPrefs(next);
    };
    chrome.storage.onChanged.addListener(onStorage);
    return () => chrome.storage.onChanged.removeListener(onStorage);
  }, []);

  useEffect(() => {
    if (!recordingState.startedAt) return;
    const id = setInterval(() => setRecNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [recordingState.startedAt]);
  const recElapsed = recordingState.startedAt
    ? `${Math.floor((recNow - recordingState.startedAt) / 60000)}:${String(
        Math.max(0, Math.floor((recNow - recordingState.startedAt) / 1000)) % 60,
      ).padStart(2, '0')}`
    : '0:00';

  const sessions = Object.values(state.sessions);
  const sorted = [...sessions].sort(
    (a, b) => new Date(b.lastUsed).getTime() - new Date(a.lastUsed).getTime(),
  );
  const activeSession = state.activeSession ? state.sessions[state.activeSession] : null;
  const quota = useQuota(health === 'connected');
  const browserStatus = useBrowserStatus(health === 'connected' && Boolean(activeSession));
  const taskBoard = useTaskBoard(health === 'connected' && state.view === 'tasks', taskDomainFilter);
  const attentionMap = useAttentionAlerts(sessions, state.activeSession, attentionPrefs);
  const activeAttention = activeSession ? attentionMap.get(activeSession.name) : undefined;
  const activeNeedsStripAttention = needsUrgentStripAttention(activeAttention);

  // Wrap raw switchSession: close any open terminal (so its PTY process is torn
  // down and never lingers in the background) and sync transcript when selecting
  // a non-streaming session.
  const switchSession = useCallback(
    (name: string) => {
      if (openTerminal && openTerminal.session !== name) {
        setOpenTerminal(null);
      }
      switchSessionBase(name);
      const session = state.sessions[name];
      const working = session
        ? deriveWorkingState(session, Boolean(findPendingPermission(session.messages))).isWorking
        : false;
      if (!working) {
        syncTranscript(name).catch(() => {});
      }
    },
    [switchSessionBase, syncTranscript, state.sessions, openTerminal],
  );

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const isMod = e.metaKey || e.ctrlKey;
      if (isMod && e.key === 'k') {
        e.preventDefault();
        setShowNewModal(true);
        return;
      }
      if (isMod && e.key >= '1' && e.key <= '9') {
        const idx = parseInt(e.key, 10) - 1;
        const target = sorted[idx];
        if (target) {
          e.preventDefault();
          switchSession(target.name);
        }
      }
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [sorted, switchSession]);

  const handleNewChat = useCallback(() => setShowNewModal(true), []);
  const handleCloseModal = useCallback(() => setShowNewModal(false), []);
  const handleNewTask = useCallback(() => setShowNewTaskModal(true), []);
  const handleCloseTaskModal = useCallback(() => setShowNewTaskModal(false), []);

  const openWorkerSession = useCallback(
    (sessionName: string) => {
      dispatch({ type: 'SET_VIEW', view: 'chat' });
      switchSession(sessionName);
    },
    [dispatch, switchSession],
  );

  const openScheduleSetupChat = useCallback(
    async (setupSessionName: string, agent: Agent) => {
      const cwd = activeSession?.cwd ?? Object.values(state.sessions)[0]?.cwd ?? '';
      if (!state.sessions[setupSessionName]) {
        try {
          await createSession({
            name: setupSessionName,
            agent,
            cwd: cwd || '/',
            purpose: 'schedule_setup',
            mode: 'inspect',
          });
        } catch {
          dispatch({
            type: 'ADD_SESSION',
            name: setupSessionName,
            agent,
            cwd: cwd || '/',
            purpose: 'schedule_setup',
          });
        }
      }
      dispatch({ type: 'SET_VIEW', view: 'chat' });
      switchSession(setupSessionName);
    },
    [activeSession, state.sessions, createSession, dispatch, switchSession],
  );

  const handleOpenTerminal = useCallback((session: string) => {
    // Always switch into that chat first. Sidebar "Terminal" uses stopPropagation,
    // so without this the PTY opens for session B while the UI still shows chat A —
    // which feels like "terminals are mixed".
    if (state.activeSession !== session) {
      switchSessionBase(session);
    }
    // Stable chat-{session} PTY — one Claude conversation per DevScope chat.
    setOpenTerminal({ terminalId: chatTerminalId(session), session });
  }, [state.activeSession, switchSessionBase]);

  const handleCloseTerminal = useCallback(() => {
    // Pull Claude JSONL into chat bubbles after PTY work (terminal was source of truth).
    if (openTerminal) {
      const name = openTerminal.session;
      mergeTranscript(name).catch(() => {});
      syncTranscript(name, true).catch(() => {});
      window.setTimeout(() => {
        mergeTranscript(name).catch(() => {});
        syncTranscript(name, true).catch(() => {});
      }, 2500);
    }
    setOpenTerminal(null);
  }, [openTerminal, syncTranscript, mergeTranscript]);

  const sidebarConnected = activeSession?.isConnected ?? false;

  const pendingPermission = activeSession
    ? findPendingPermission(activeSession.messages)
    : undefined;
  const awaitingApproval = Boolean(pendingPermission);
  const workingState = activeSession
    ? deriveWorkingState(activeSession, awaitingApproval)
    : null;
  const composerDisabled = !activeSession;

  const useTerminalFirst = Boolean(
    activeSession
      && uiPrefs.interactionMode === 'terminal'
      && !isAutomationSession(activeSession.name),
  );
  const streamPtyActive = Boolean(
    openTerminal
      && activeSession
      && openTerminal.session === activeSession.name,
  );
  // Guard: never keep a PTY overlay bound to a chat that is not the active one.
  useEffect(() => {
    if (!openTerminal || !activeSession) return;
    if (openTerminal.session !== activeSession.name) {
      setOpenTerminal(null);
    }
  }, [openTerminal, activeSession?.name]);

  const ptyLive = useTerminalFirst || streamPtyActive;
  const ptyBinding = usePtySession(activeSession?.name ?? null, ptyLive);

  useEffect(() => {
    setTerminalModeSession(
      ptyLive && activeSession ? activeSession.name : null,
    );
  }, [ptyLive, activeSession?.name, setTerminalModeSession]);

  const handleTerminalSend = useCallback(
    (
      text: string,
      opts?: { context?: import('@/shared/frames').MessageContext; mode?: import('@/shared/frames').AgentMode; model?: string },
    ) => {
      if (!activeSession || !ptyBinding) return;
      void sendMessageViaPty(activeSession.name, text, ptyBinding.terminalRef, opts);
    },
    [activeSession, ptyBinding, sendMessageViaPty],
  );

  const [boundTabStale, setBoundTabStale] = useState(false);
  useEffect(() => {
    const tab = activeSession?.boundTab;
    if (!tab) {
      setBoundTabStale(false);
      return;
    }
    chrome.tabs.get(tab.tabId).then(
      () => setBoundTabStale(false),
      () => setBoundTabStale(true),
    );
    const id = setInterval(() => {
      chrome.tabs.get(tab.tabId).then(
        () => setBoundTabStale(false),
        () => setBoundTabStale(true),
      );
    }, 5000);
    return () => clearInterval(id);
  }, [activeSession?.boundTab?.tabId]);

  const sidebar = (
    <SessionSidebar
      sessions={sorted}
      activeSession={state.activeSession}
      onSelect={switchSession}
      onNewChat={handleNewChat}
      onNewTask={handleNewTask}
      onDelete={deleteSession}
      onOpenTerminal={handleOpenTerminal}
      onSettingsClick={() => {
        setShowGlossary(false);
        setShowSettings((v) => !v);
      }}
      onGlossaryClick={() => {
        setShowSettings(false);
        setShowGlossary((v) => !v);
      }}
      isConnected={sidebarConnected}
      attentionBySession={attentionMap}
    />
  );

  const newSessionModal = showNewModal && (
    <NewSessionModal
      existingNames={sessions.map((s) => s.name)}
      onSubmit={createSession}
      onClose={handleCloseModal}
    />
  );

  const newTaskModal = showNewTaskModal && (
    <NewTaskModal onClose={handleCloseTaskModal} />
  );

  if (showSettings) {
    return (
      <div className="flex h-screen overflow-hidden">
        {sidebar}
        <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
          <Settings onClose={() => setShowSettings(false)} />
        </div>
        {newSessionModal}
        {newTaskModal}
      </div>
    );
  }

  if (showGlossary) {
    return (
      <div className="flex h-screen overflow-hidden">
        {sidebar}
        <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
          <Glossary onClose={() => setShowGlossary(false)} />
        </div>
        {newSessionModal}
        {newTaskModal}
      </div>
    );
  }

  return (
    <div className="flex h-screen overflow-hidden">
      {sidebar}

      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <ViewNav view={state.view} dispatch={dispatch} />

        {state.view === 'chat' ? (
          sessions.length === 0 && health !== 'connected' ? (
            <Onboarding
              health={health}
              onRecheck={recheck}
              onOpenSettings={() => setShowSettings(true)}
            />
          ) : sessions.length === 0 ? (
            <EmptyState onNewChat={handleNewChat} />
          ) : !activeSession ? (
            <SelectState />
          ) : (
            <>
              <SessionBar
                name={activeSession.name}
                cwd={activeSession.cwd}
                isConnected={activeSession.isConnected}
                usageTotal={activeSession.usageTotal}
                contextTokens={activeSession.contextTokens}
                quota={quota}
                onReconnect={() => void reconnectSession(activeSession.name)}
              />
              {uiPrefs.productMode === 'consumer' && (
                <CapabilitiesStrip onOpenSettings={() => setShowSettings(true)} />
              )}
              {useTerminalFirst && ptyBinding ? (
                <TerminalSessionView
                  session={activeSession}
                  pty={ptyBinding}
                  boundTabStale={boundTabStale}
                  browser={browserStatus}
                  onReconnectExtension={() => void reconnectSession(activeSession.name)}
                  onBindTab={(tabId) => void bindSessionTab(activeSession.name, tabId)}
                  onDismissTabPick={() => clearTabPick(activeSession.name)}
                  onBoundTabChange={(tab) => setBoundTabState(activeSession.name, tab)}
                  onSendViaPty={handleTerminalSend}
                  onOpenGlossary={() => setShowGlossary(true)}
                  onReset={() => resetSession(activeSession.name)}
                  recording={recordingState.recording}
                  recordingPending={recordingState.recordingPending}
                  recordingError={recordingState.error}
                  recElapsed={recElapsed}
                  onToggleRecording={recordingState.toggle}
                />
              ) : (
                <>
              <BrowserContextStrip
                isSessionConnected={activeSession.isConnected}
                boundTab={activeSession.boundTab}
                boundTabStale={boundTabStale}
                browser={browserStatus}
                extensionDisconnected={activeSession.browserExtensionDisconnected}
                onRebind={() => {
                  const pill = document.querySelector('[title*="Choose which browser tab"]');
                  if (pill instanceof HTMLElement) pill.click();
                }}
                onReconnectExtension={() => void reconnectSession(activeSession.name)}
              />
              {streamPtyActive && openTerminal && (
                <TerminalView
                  key={openTerminal.terminalId}
                  ref={ptyBinding?.terminalRef}
                  terminalId={openTerminal.terminalId}
                  cmd="resume"
                  session={openTerminal.session}
                  onClose={handleCloseTerminal}
                  className="min-h-0 flex-1"
                />
              )}
              {!streamPtyActive && activeSession.tabPickPrompt && (
                <TabPickBanner
                  reason={activeSession.tabPickPrompt.reason}
                  hintUrl={activeSession.tabPickPrompt.hintUrl}
                  candidates={activeSession.tabPickPrompt.candidates}
                  onPick={(tabId) => void bindSessionTab(activeSession.name, tabId)}
                  onDismiss={() => clearTabPick(activeSession.name)}
                />
              )}
              {!streamPtyActive && (
                <>
              <ActivityStrip
                statusLabel={workingState?.statusLabel ?? ''}
                turnStartedAt={activeSession.turnStartedAt}
                isWorking={workingState?.isWorking ?? false}
                queuedSteeringCount={workingState?.queuedSteeringCount ?? 0}
                usageTotal={activeSession.usageTotal}
                onReset={() => resetSession(activeSession.name)}
                onInterrupt={() => interrupt(activeSession.name)}
                needsAttention={activeNeedsStripAttention}
                attentionLabel={activeAttention?.label}
                currentTool={activeSession.currentTool}
                lastOutputAt={activeSession.lastOutputAt}
                onMedic={() => sendMessage(activeSession.name, '/medic')}
              />
              {shouldWarnCompact(activeSession) && (
                <CompactBanner
                  tokens={activeSession.usageTotal?.tokens ?? 0}
                  onCompactNow={() => compactSession(activeSession.name)}
                  onDismiss={() => dismissCompactBanner(activeSession.name)}
                />
              )}
              {uiPrefs.streamDebug && <StreamDebugPanel session={activeSession} />}
              {activeSession.coachHint && (
                <SessionCoachBanner
                  hint={activeSession.coachHint}
                  onSwitchModel={(modelId) => {
                    void setSessionModel(activeSession.name, modelId).then(() => {
                      dispatch({ type: 'SET_SESSION_MODEL', session: activeSession.name, model: modelId });
                      dispatch({ type: 'DISMISS_COACH', session: activeSession.name });
                    });
                  }}
                  onCompact={() => {
                    void requestSessionCompact(activeSession.name).then(() => {
                      dispatch({
                        type: 'SESSION_COMMAND',
                        session: activeSession.name,
                        id: `manual-compact-${Date.now()}`,
                        text: 'Compact',
                        hint: 'Summarized on demand — next message uses the summary.',
                      });
                      dispatch({ type: 'DISMISS_COACH', session: activeSession.name });
                    });
                  }}
                  onDismiss={() => dispatch({ type: 'DISMISS_COACH', session: activeSession.name })}
                />
              )}
              <Chat
                messages={activeSession.messages}
                isLoadingHistory={activeSession.isLoadingHistory}
                agent={activeSession.agent}
                sessionName={activeSession.name}
                statusLabel={workingState?.statusLabel}
                queuedSteeringCount={workingState?.queuedSteeringCount ?? 0}
                reconnecting={state.reconnecting}
                bridgeUnreachable={state.bridgeUnreachable}
                stickyPermissionId={pendingPermission?.actionId}
                onRespondPermission={respondPermission}
                onOpenTerminal={handleOpenTerminal}
                onRetryMessage={retryMessage}
                onCancelSteering={cancelSteering}
              />
              {pendingPermission && (
                <DecisionPanel
                  message={pendingPermission}
                  sessionName={activeSession.name}
                  onRespond={respondPermission}
                />
              )}
                </>
              )}
              {/* Composer stays visible in terminal overlay too — tools (attach/mic/mode) still useful. */}
              <Composer
                sessionName={activeSession.name}
                agent={activeSession.agent}
                sessionModel={activeSession.model}
                sessionClaudeAgent={activeSession.claude_agent}
                showStop={streamPtyActive ? false : (workingState?.showStop ?? false)}
                messages={activeSession.messages}
                hideQuickReplies={streamPtyActive}
                onSend={
                  streamPtyActive
                    ? (_name, text, opts) => handleTerminalSend(text, opts)
                    : sendMessage
                }
                onOpenGlossary={() => setShowGlossary(true)}
                onReset={resetSession}
                onBoundTabChange={(tab) => setBoundTabState(activeSession.name, tab)}
                recording={recordingState.recording}
                recordingPending={recordingState.recordingPending}
                recordingError={recordingState.error}
                recElapsed={recElapsed}
                onToggleRecording={recordingState.toggle}
                disabled={composerDisabled}
              />
                </>
              )}
            </>
          )
        ) : state.view === 'whatsapp' ? (
          <WhatsAppCockpit sessionName={state.activeSession} />
        ) : state.view === 'tasks' ? (
          <TaskBoard
            board={taskBoard.board}
            loading={taskBoard.loading}
            error={taskBoard.error}
            sessionNames={sessions.map((s) => s.name)}
            activeSession={state.activeSession}
            onOpenSetupChat={(name, agent) => void openScheduleSetupChat(name, agent)}
            domainFilter={taskDomainFilter}
            onDomainFilterChange={setTaskDomainFilter}
            onRefresh={() => void taskBoard.refresh()}
            onNewTask={handleNewTask}
            onOpenWorkerSession={openWorkerSession}
          />
        ) : state.view === 'email' ? (
          <EmailCockpit />
        ) : state.view === 'calendar' ? (
          <CalendarCockpit />
        ) : state.view === 'meta_ads' ? (
          <MetaAdsCockpit />
        ) : null}
      </div>

      {newSessionModal}
      {newTaskModal}
    </div>
  );
}

interface SessionBarProps {
  name: string;
  cwd: string;
  isConnected: boolean;
  usageTotal?: { tokens: number; costUsd: number };
  contextTokens?: number;
  quota?: QuotaInfo | null;
  onReconnect: () => void;
}

function SessionBar({ name, cwd, isConnected, usageTotal, contextTokens, quota, onReconnect }: SessionBarProps) {
  const folder = cwd ? cwd.split('/').filter(Boolean).slice(-1)[0] : '';
  const tokens = usageTotal?.tokens ?? 0;
  return (
    <div className="flex shrink-0 items-center gap-2 border-b border-line bg-surface-raised px-3 py-2">
      <span className="truncate text-sm font-semibold text-fg" title={name}>
        {name}
      </span>
      {folder && (
        <span className="truncate font-mono text-2xs text-fg-subtle" title={cwd}>
          {folder}
        </span>
      )}
      <div className="ml-auto flex flex-shrink-0 items-center gap-2">
        {quota && quota.available && <GlobalBattery quota={quota} />}
        {contextTokens != null && contextTokens > 0 && (
          <TokenBattery contextTokens={contextTokens} />
        )}
        {tokens > 0 && (
          <span
            className="font-mono text-2xs text-fg-subtle"
            title="Total tokens · cost this session"
          >
            {tokens >= 1000 ? `${(tokens / 1000).toFixed(1)}k` : tokens}·${usageTotal!.costUsd.toFixed(2)}
          </span>
        )}
      </div>
      {!isConnected && (
        <span className="flex items-center gap-1 text-2xs font-medium text-warning">
          <span className="h-1.5 w-1.5 rounded-full bg-warning animate-cursor-pulse" aria-hidden />
          Reconnecting…
        </span>
      )}
      {!isConnected && (
        <button
          onClick={onReconnect}
          className="flex items-center gap-1 rounded-sm px-1.5 py-0.5 text-2xs font-medium text-signal transition-colors duration-fast ease-tool hover:bg-signal-subtle"
        >
          <RotateCw size={11} strokeWidth={2.25} />
          Reconnect
        </button>
      )}
    </div>
  );
}

const CAPABILITIES = [
  { icon: MessageSquareCode, label: 'Chat with code' },
  { icon: Camera, label: 'Screenshot page' },
  { icon: MousePointerClick, label: 'Inspect elements' },
] as const;

function EmptyState({ onNewChat }: { onNewChat: () => void }) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-5 px-6 text-center">
      <Logomark className="h-10 w-10 text-signal" />
      <div className="space-y-1.5">
        <p className="text-lg font-semibold tracking-tight text-fg">Your AI dev agent, right here.</p>
        <p className="text-sm leading-[1.55] text-fg-muted">
          Connect a Claude or Cursor session and chat with your codebase while you browse.
        </p>
      </div>
      <div className="flex flex-col items-center gap-1.5">
        <button
          onClick={onNewChat}
          className="flex h-10 items-center gap-1.5 rounded-md bg-signal px-5 text-sm font-medium text-signal-contrast transition-colors duration-fast ease-tool hover:bg-signal-hover"
        >
          Create your first chat
        </button>
        <span className="text-2xs text-fg-subtle">or press ⌘K</span>
      </div>
      <div className="flex flex-wrap items-center justify-center gap-1.5 pt-2">
        {CAPABILITIES.map((cap) => (
          <span
            key={cap.label}
            className="flex items-center gap-1 rounded-sm border border-line px-2 py-1 text-2xs text-fg-muted"
          >
            <cap.icon size={12} strokeWidth={2} />
            {cap.label}
          </span>
        ))}
      </div>
    </div>
  );
}

function SelectState() {
  return (
    <div className="flex flex-1 items-center justify-center text-xs text-fg-subtle">
      Select a session from the sidebar
    </div>
  );
}
