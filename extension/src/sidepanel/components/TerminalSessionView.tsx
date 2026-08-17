/**
 * TerminalSessionView — terminal-first chat layout.
 *
 * Full-height interactive Claude TUI + the same Composer/attach toolbar as stream mode.
 */
import { useCallback } from 'react';
import type { Ref } from 'react';
import type { AgentMode, MessageContext } from '@/shared/frames';
import type { SessionState } from '../store/sessionStore';
import type { BrowserStatus } from '../hooks/useBrowserStatus';
import type { PtySessionBinding } from '../hooks/usePtySession';
import { BrowserContextStrip } from './BrowserContextStrip';
import { TabPickBanner } from './TabPickBanner';
import { TerminalView, type TerminalViewHandle } from './TerminalView';
import { Composer } from './Composer';
import type { BoundTab } from '@/shared/tabBinding';

interface TerminalSessionViewProps {
  session: SessionState;
  pty: PtySessionBinding;
  boundTabStale: boolean;
  browser: BrowserStatus;
  onReconnectExtension: () => void;
  onBindTab: (tabId: number) => void;
  onDismissTabPick: () => void;
  onBoundTabChange: (tab: BoundTab | null) => void;
  onSendViaPty: (
    text: string,
    opts?: { context?: MessageContext; mode?: AgentMode; model?: string },
  ) => void;
  onOpenGlossary: () => void;
  onReset: () => void;
  recording: boolean;
  recordingPending: boolean;
  recordingError: string | null;
  recElapsed: string;
  onToggleRecording: () => void;
}

export function TerminalSessionView({
  session,
  pty,
  boundTabStale,
  browser,
  onReconnectExtension,
  onBindTab,
  onDismissTabPick,
  onBoundTabChange,
  onSendViaPty,
  onOpenGlossary,
  onReset,
  recording,
  recordingPending,
  recordingError,
  recElapsed,
  onToggleRecording,
}: TerminalSessionViewProps) {
  const handleSend = useCallback(
    (
      sessionName: string,
      text: string,
      opts?: { context?: MessageContext; mode?: AgentMode; model?: string },
    ) => {
      if (sessionName !== session.name) return;
      onSendViaPty(text, opts);
    },
    [onSendViaPty, session.name],
  );

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
      <BrowserContextStrip
        isSessionConnected={session.isConnected}
        boundTab={session.boundTab}
        boundTabStale={boundTabStale}
        browser={browser}
        extensionDisconnected={session.browserExtensionDisconnected}
        onRebind={() => {
          const pill = document.querySelector('[title*="Choose which browser tab"]');
          if (pill instanceof HTMLElement) pill.click();
        }}
        onReconnectExtension={onReconnectExtension}
      />
      {session.tabPickPrompt && (
        <TabPickBanner
          reason={session.tabPickPrompt.reason}
          hintUrl={session.tabPickPrompt.hintUrl}
          candidates={session.tabPickPrompt.candidates}
          onPick={(tabId) => onBindTab(tabId)}
          onDismiss={onDismissTabPick}
        />
      )}
      <TerminalView
        key={pty.terminalId}
        ref={pty.terminalRef as Ref<TerminalViewHandle>}
        terminalId={pty.terminalId}
        cmd="resume"
        session={pty.session}
        onClose={() => {}}
        embedded
        className="min-h-0 flex-1"
      />
      <Composer
        sessionName={session.name}
        agent={session.agent}
        sessionModel={session.model}
        sessionClaudeAgent={session.claude_agent}
        showStop={false}
        messages={session.messages}
        hideQuickReplies
        onSend={handleSend}
        onOpenGlossary={onOpenGlossary}
        onReset={onReset}
        onBoundTabChange={onBoundTabChange}
        recording={recording}
        recordingPending={recordingPending}
        recordingError={recordingError ?? undefined}
        recElapsed={recElapsed}
        onToggleRecording={onToggleRecording}
        disabled={false}
      />
    </div>
  );
}
