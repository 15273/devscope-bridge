/**
 * TerminalView — xterm.js terminal wired to the bridge PTY WebSocket.
 *
 * Props:
 *   terminalId  — unique id for this PTY instance (^[a-zA-Z0-9_-]{1,64}$)
 *   cmd         — "resume" | "claude" | "shell"
 *   session     — DevScope session name (required when cmd === "resume")
 *   onClose     — called when the user closes the panel
 *   embedded    — hide close button (terminal-first chat layout)
 *
 * Ref API:
 *   write(data) — inject keystrokes/text into the PTY WS
 *   isOpen()    — whether the PTY WebSocket is connected
 *
 * Protocol (JSON frames over ws://127.0.0.1:7878/pty/{terminalId}?token=…):
 *   server→client: {type:"pty_output",data:string} | {type:"pty_exit"} | {type:"pty_error",message:string}
 *   client→server: {type:"pty_input",data:string} | {type:"pty_resize",cols:number,rows:number}
 */
import {
  forwardRef,
  useEffect,
  useRef,
  useState,
  useCallback,
  useImperativeHandle,
} from 'react';
import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import '@xterm/xterm/css/xterm.css';
import { X, RotateCw } from 'lucide-react';
import { BRIDGE_HTTP, getToken } from '../bridge';

export type PtyCmd = 'resume' | 'claude' | 'shell';

export interface TerminalViewHandle {
  write: (data: string) => void;
  isOpen: () => boolean;
}

export interface TerminalViewProps {
  terminalId: string;
  cmd: PtyCmd;
  session?: string;
  onClose: () => void;
  className?: string;
  /** When true, terminal is the main chat surface — no dismiss button. */
  embedded?: boolean;
}

type ConnectionState = 'connecting' | 'open' | 'closed' | 'error';

/** Build the PTY WebSocket URL reusing bridge's host/port and token scheme. */
function buildPtyUrl(terminalId: string, cmd: PtyCmd, session: string | undefined, token: string): string {
  const wsBase = BRIDGE_HTTP.replace(/^http/, 'ws');
  const params = new URLSearchParams({ token });
  params.set('cmd', cmd);
  if (session) params.set('session', session);
  return `${wsBase}/pty/${encodeURIComponent(terminalId)}?${params.toString()}`;
}

/** Graphite-themed xterm options. Colors pulled from tailwind.css tokens:
 *  background → --surface-base dark  #0F0F0F
 *  cursor     → --signal dark         #FB923C  (amber)
 *  foreground → --fg-primary dark     #F4F4F5
 *  selection  → --signal-subtle dark  rgba(251,146,60,0.18)
 */
function makeTerminalOptions(): ConstructorParameters<typeof Terminal>[0] {
  const isDark = document.documentElement.classList.contains('dark') ||
    document.documentElement.classList.contains('dim');

  // Light vs dark surface values
  const bg = isDark ? '#0F0F0F' : '#FAFAFA';
  const fg = isDark ? '#F4F4F5' : '#18181B';
  const cursor = isDark ? '#FB923C' : '#E86D13';
  const selBg = isDark ? '#FB923C30' : '#E86D1330';
  const brightBlack = isDark ? '#71717A' : '#71717A';
  const brightWhite = isDark ? '#FFFFFF' : '#000000';

  return {
    fontFamily: '"JetBrains Mono Variable", "JetBrains Mono", ui-monospace, Menlo, monospace',
    // Slightly smaller → more cols in the narrow Chrome side panel (Ink TUI
    // needs enough width or agent trees / token counters scatter).
    fontSize: 11,
    lineHeight: 1.1,
    letterSpacing: 0,
    cursorBlink: true,
    cursorStyle: 'bar',
    theme: {
      background: bg,
      foreground: fg,
      cursor,
      cursorAccent: bg,
      selectionBackground: selBg,
      black: '#18181B',
      brightBlack,
      red: '#EF4444',
      brightRed: '#F87171',
      green: '#16A34A',
      brightGreen: '#4ADE80',
      yellow: '#D97706',
      brightYellow: '#FCD34D',
      blue: '#3B82F6',
      brightBlue: '#93C5FD',
      magenta: '#A855F7',
      brightMagenta: '#D8B4FE',
      cyan: '#06B6D4',
      brightCyan: '#67E8F9',
      white: '#D4D4D8',
      brightWhite,
    },
    scrollback: 5000,
    allowTransparency: false,
    convertEol: false,
  };
}

export const TerminalView = forwardRef<TerminalViewHandle, TerminalViewProps>(function TerminalView(
  { terminalId, cmd, session, onClose, className, embedded = false },
  ref,
) {
  const containerRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<Terminal | null>(null);
  const fitRef = useRef<FitAddon | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const observerRef = useRef<ResizeObserver | null>(null);

  const [connState, setConnState] = useState<ConnectionState>('connecting');
  const [errorMsg, setErrorMsg] = useState('');
  const [reconnectKey, setReconnectKey] = useState(0);

  const sendResize = useCallback((ws: WebSocket, term: Terminal) => {
    if (ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify({ type: 'pty_resize', cols: term.cols, rows: term.rows }));
  }, []);

  const writeToPty = useCallback((data: string) => {
    const socket = wsRef.current;
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: 'pty_input', data }));
    }
  }, []);

  useImperativeHandle(
    ref,
    () => ({
      write: writeToPty,
      isOpen: () => wsRef.current?.readyState === WebSocket.OPEN,
    }),
    [writeToPty],
  );

  useEffect(() => {
    if (!containerRef.current) return;

    let disposed = false;

    // ── 1. Create Terminal + FitAddon ──────────────────────────────────────
    const term = new Terminal(makeTerminalOptions());
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(containerRef.current);
    termRef.current = term;
    fitRef.current = fit;

    // Refit when the panel geometry or font metrics change. Debounced during
    // drag-resize so Claude's Ink TUI gets one SIGWINCH, not dozens mid-frame.
    let rafId = 0;
    let debounceTimer = 0;
    let lastCols = -1;
    let lastRows = -1;

    const applyFit = () => {
      if (disposed || !containerRef.current) return;
      try {
        fit.fit();
        const cols = term.cols;
        const rows = term.rows;
        // Never clear() the buffer — Claude's Ink TUI does not fully redraw after
        // a wipe, so clear() left users with a blank/garbled panel. SIGWINCH via
        // pty_resize is enough for Claude to reflow when geometry actually changes.
        if (cols === lastCols && rows === lastRows) return;
        lastCols = cols;
        lastRows = rows;

        const socket = wsRef.current;
        if (socket?.readyState === WebSocket.OPEN) sendResize(socket, term);
      } catch {
        /* container detached mid-fit — ignore */
      }
    };

    const fitNow = () => {
      cancelAnimationFrame(rafId);
      clearTimeout(debounceTimer);
      applyFit();
    };

    const scheduleFit = () => {
      cancelAnimationFrame(rafId);
      rafId = requestAnimationFrame(() => {
        clearTimeout(debounceTimer);
        debounceTimer = window.setTimeout(applyFit, 120);
      });
    };

    fitNow();
    document.fonts?.ready?.then(fitNow).catch(() => {});

    // ── 2. Open PTY WebSocket only after the host has a real size ───────────
    // Spawning Claude before FitAddon has stable cols/rows is the main cause of
    // "scattered" Ink TUI (timestamps/tokens floating to the right).
    let ws: WebSocket;
    let hadPtyError = false;
    let stabilizeTimer = 0;

    const writePty = (raw: string) => {
      term.write(raw);
    };

    const waitForLayout = async (): Promise<void> => {
      for (let i = 0; i < 30; i += 1) {
        if (disposed) return;
        fitNow();
        const el = containerRef.current;
        if (el && el.clientWidth >= 80 && el.clientHeight >= 40 && term.cols >= 40) {
          return;
        }
        await new Promise((r) => window.setTimeout(r, 50));
      }
      fitNow();
    };

    getToken().then(async (token) => {
      if (disposed) return;
      await waitForLayout();
      if (disposed) return;
      const url = buildPtyUrl(terminalId, cmd, session, token);
      ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        if (disposed) { ws.close(); return; }
        fitNow();
        sendResize(ws, term);
        // Second SIGWINCH after fonts/layout settle — Claude Ink reflows once.
        clearTimeout(stabilizeTimer);
        stabilizeTimer = window.setTimeout(() => {
          if (disposed || ws.readyState !== WebSocket.OPEN) return;
          fitNow();
          sendResize(ws, term);
        }, 280);
        setConnState('open');
      };

      ws.onmessage = (evt) => {
        if (disposed) return;
        try {
          const frame = JSON.parse(evt.data as string) as {
            type: string;
            data?: string;
            message?: string;
          };
          if (frame.type === 'pty_output' && frame.data != null) {
            writePty(frame.data);
          } else if (frame.type === 'pty_exit') {
            term.writeln('\r\n\x1b[2m[process exited]\x1b[0m');
            setConnState('closed');
          } else if (frame.type === 'pty_error') {
            hadPtyError = true;
            term.writeln(`\r\n\x1b[31m[error: ${frame.message ?? 'unknown'}]\x1b[0m`);
            setErrorMsg(frame.message ?? 'PTY error');
            setConnState('error');
          }
        } catch {
          // Non-JSON frame — ignore
        }
      };

      ws.onerror = () => {
        if (disposed) return;
        hadPtyError = true;
        setConnState('error');
        setErrorMsg('WebSocket connection failed. Is the bridge running?');
      };

      ws.onclose = (evt) => {
        if (disposed) return;
        if (!hadPtyError) {
          setConnState(evt.wasClean ? 'closed' : 'error');
          if (!evt.wasClean) setErrorMsg('Connection closed unexpectedly.');
        }
      };
    }).catch(() => {
      setConnState('error');
      setErrorMsg('Could not retrieve bridge token.');
    });

    // ── 3. Forward keystrokes ──────────────────────────────────────────────
    const dataDispose = term.onData((data: string) => {
      writeToPty(data);
    });

    // ── 4. Resize handling → fit() + pty_resize ────────────────────────────
    // ResizeObserver catches container/flex changes; the window 'resize'
    // listener is a backstop for side-panel width drags that don't always
    // bubble to the inner element as a border-box change.
    const ro = new ResizeObserver(scheduleFit);
    const host = containerRef.current;
    ro.observe(host);
    if (host.parentElement) ro.observe(host.parentElement);
    observerRef.current = ro;
    window.addEventListener('resize', scheduleFit);

    // ── Cleanup ────────────────────────────────────────────────────────────
    return () => {
      disposed = true;
      cancelAnimationFrame(rafId);
      clearTimeout(debounceTimer);
      clearTimeout(stabilizeTimer);
      window.removeEventListener('resize', scheduleFit);
      dataDispose.dispose();
      ro.disconnect();
      ws?.close();
      try {
        term.reset();
      } catch {
        /* detached */
      }
      term.dispose();
      termRef.current = null;
      fitRef.current = null;
      wsRef.current = null;
    };
  }, [terminalId, cmd, session, reconnectKey, sendResize, writeToPty]);

  const handleReconnect = useCallback(() => {
    setErrorMsg('');
    setConnState('connecting');
    setReconnectKey((k) => k + 1);
  }, []);

  return (
    <div
      dir="ltr"
      className={`flex flex-col overflow-hidden bg-surface ${className ?? 'h-full min-h-0 flex-1'}`}
    >
      {/* ── Header bar ─────────────────────────────────────────────────── */}
      <div className="flex shrink-0 items-center gap-2 border-b border-line bg-surface-raised px-3 py-1.5">
        <span className="flex items-center gap-1.5 text-xs font-medium text-fg-muted">
          <TerminalIcon />
          {embedded ? 'Claude' : 'Terminal'}
          {session && (
            <span className="font-mono text-2xs text-fg-subtle">· {session}</span>
          )}
        </span>

        <ConnectionBadge state={connState} />

        <div className="ml-auto flex items-center gap-1">
          {(connState === 'closed' || connState === 'error') && (
            <button
              onClick={handleReconnect}
              title="Reconnect terminal"
              className="flex items-center gap-1 rounded-sm border border-line px-1.5 py-0.5 text-2xs text-fg-muted transition-colors duration-fast ease-tool hover:border-signal/40 hover:bg-signal-subtle hover:text-signal"
            >
              <RotateCw size={11} strokeWidth={2.25} />
              Reconnect
            </button>
          )}
          {!embedded && (
            <button
              onClick={onClose}
              aria-label="Close terminal"
              title="Close terminal"
              className="flex h-6 w-6 items-center justify-center rounded-md text-fg-subtle transition-colors duration-fast ease-tool hover:bg-surface-overlay hover:text-fg"
            >
              <X size={13} strokeWidth={2} />
            </button>
          )}
        </div>
      </div>

      {/* ── Error banner ───────────────────────────────────────────────── */}
      {errorMsg && (
        <div className="shrink-0 border-b border-danger/20 bg-danger-subtle px-3 py-1.5 text-2xs text-danger">
          {errorMsg}
        </div>
      )}

      {/* ── xterm container ────────────────────────────────────────────── */}
      <div
        ref={containerRef}
        dir="ltr"
        className="terminal-xterm-host min-h-0 flex-1 overflow-hidden"
        aria-label="Terminal"
        role="application"
      />
    </div>
  );
});

// ── Small internal helpers ─────────────────────────────────────────────────

function TerminalIcon() {
  return (
    <svg
      width="13"
      height="13"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <polyline points="3 6 6 9 3 12" />
      <line x1="9" y1="12" x2="13" y2="12" />
    </svg>
  );
}

function ConnectionBadge({ state }: { state: ConnectionState }) {
  if (state === 'connecting') {
    return (
      <span className="flex items-center gap-1 rounded-sm bg-signal-subtle px-1.5 py-0.5 text-[10px] font-medium text-signal">
        <span className="h-1.5 w-1.5 rounded-full bg-signal animate-cursor-pulse" aria-hidden />
        connecting
      </span>
    );
  }
  if (state === 'open') {
    return (
      <span className="flex items-center gap-1 rounded-sm bg-success-subtle px-1.5 py-0.5 text-[10px] font-medium text-success">
        <span className="h-1.5 w-1.5 rounded-full bg-success" aria-hidden />
        connected
      </span>
    );
  }
  if (state === 'closed') {
    return (
      <span className="rounded-sm bg-surface-overlay px-1.5 py-0.5 text-[10px] font-medium text-fg-subtle">
        closed
      </span>
    );
  }
  return (
    <span className="rounded-sm bg-danger-subtle px-1.5 py-0.5 text-[10px] font-medium text-danger">
      error
    </span>
  );
}
