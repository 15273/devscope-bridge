/**
 * Composer — message input: context chips, page-state attach toolbar, element
 * picker, operational-mode pill, `/` command menu, and send-with-context.
 *
 * Keyboard: Cmd/Ctrl+Enter or Enter → send; Shift+Enter → newline.
 * When the `/` menu is open, ↑/↓ navigate, Enter selects, Esc dismisses.
 */
import { useState, useRef, useCallback, useEffect, useMemo, ClipboardEvent, KeyboardEvent } from 'react';
import {
  CornerDownLeft,
  Crosshair,
  Image as ImageIcon,
  Mic,
  MicOff,
  Paperclip,
  Send,
  Video,
} from 'lucide-react';
import type {
  Agent,
  AgentMode,
  ElementContext,
  MessageContext,
  PageAttachment,
  PageAttachmentKind,
} from '@/shared/frames';
import type { ChatMessage } from '../store/sessionStore';
import type { BrowseBackend } from '@/shared/browseBackend';
import {
  loadDraft,
  saveDraft,
  loadComposerContext,
  saveComposerContext,
  loadMode,
  saveMode,
  loadModel,
  saveModel,
  loadClaudeAgent,
  saveClaudeAgent,
  loadBrowseBackend,
  saveBrowseBackend,
  loadDictationPrefs,
  saveDictationPrefs,
  type DictationLang,
} from '../utils/storage';
import { fetchCommands, setSessionModel, setSessionClaudeAgent, type SlashCommand } from '../bridge';
import { ContextChips } from './composer/ContextChips';
import { fileToImageAttachment, imageFilesFromDataTransfer } from './composer/imageAttachment';
import { BrowseBackendPill } from './composer/BrowseBackendPill';
import { BoundTabPill } from './composer/BoundTabPill';
import { ModePill } from './composer/ModePill';
import { ModelPill } from './composer/ModelPill';
import { SubagentPill } from './composer/SubagentPill';
import { SlashMenu } from './composer/SlashMenu';
import { QuickChoiceBar } from './composer/QuickChoiceBar';
import { quickRepliesFromMessages } from '../utils/parseNumberedChoices';
import {
  ATTACH_ACTIONS,
  NATIVE_COMMANDS,
  isDisabledCommand,
  isNativeCommand,
  toAttachment,
} from './composer/commands';
import { useSpeechRelay } from '../hooks/useSpeechRelay';
import { useUiPrefs } from '../hooks/useUiPrefs';
import { resolveSpeechLocale, speechLocaleFromPreference } from '../utils/speech/speechLocale';
import { isTtsPlaying } from '../utils/speech/speechSynthesisCompat';
const MAX_CHARS = 8000;

/** Serialize chat messages to Markdown and trigger a browser download. */
function downloadChatMarkdown(sessionName: string, msgs: ChatMessage[]): void {
  const lines: string[] = [`# DevScope chat — ${sessionName}`, ''];
  for (const m of msgs) {
    if (m.role === 'user') {
      lines.push(`**User**`);
      lines.push('');
      lines.push(m.text);
      lines.push('');
    } else if (m.role === 'assistant') {
      lines.push(`**Assistant**`);
      lines.push('');
      lines.push(m.text || '_(no text)_');
      lines.push('');
    } else if (m.role === 'slash_cmd') {
      lines.push('```');
      lines.push(`[${m.slashTitle ?? m.role}]`);
      if (m.text) lines.push(m.text);
      lines.push('```');
      lines.push('');
    }
  }
  const md = lines.join('\n');
  const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `devscope-${sessionName}-${msgs.filter((m) => m.role === 'user' || m.role === 'assistant').length}turns.md`;
  a.click();
  URL.revokeObjectURL(url);
}
export interface SendOptions {
  context?: MessageContext;
  mode?: AgentMode;
  model?: string;
}

interface ComposerProps {
  sessionName: string;
  agent: Agent;
  /** Bridge metadata — drives model pill when session list poll updates. */
  sessionModel?: string | null;
  sessionClaudeAgent?: string | null;
  showStop: boolean;
  /** Current session messages — used only by /export. */
  messages?: ChatMessage[];
  onSend: (sessionName: string, text: string, opts?: SendOptions) => void;
  onOpenGlossary: () => void;
  onReset: (sessionName: string) => void;
  onBoundTabChange?: (tab: import('@/shared/tabBinding').BoundTab | null) => void;
  recording: boolean;
  recordingPending?: boolean;
  recordingError?: string;
  recElapsed: string;
  onToggleRecording: () => void;
  disabled?: boolean;
  /** Hide numbered quick-reply chips (terminal mode — PTY is source of truth). */
  hideQuickReplies?: boolean;
}

export function Composer({
  sessionName,
  agent,
  sessionModel,
  sessionClaudeAgent,
  showStop,
  messages = [],
  onSend,
  onOpenGlossary,
  onReset,
  onBoundTabChange,
  recording,
  recordingPending = false,
  recordingError = '',
  recElapsed,
  onToggleRecording,
  disabled = false,
  hideQuickReplies = false,
}: ComposerProps) {
  const [value, setValue] = useState('');
  const [annotating, setAnnotating] = useState(false);
  const [pickHint, setPickHint] = useState('');
  const [elements, setElements] = useState<ElementContext[]>([]);
  const [attachments, setAttachments] = useState<PageAttachment[]>([]);
  const [mode, setMode] = useState<AgentMode>('act');
  const [model, setModel] = useState<string | null>(null);
  const [claudeAgent, setClaudeAgent] = useState<string | null>(null);
  const [browseBackend, setBrowseBackend] = useState<BrowseBackend>('auto');
  const [commands, setCommands] = useState<SlashCommand[]>([]);
  const uiPrefs = useUiPrefs();
  const [slashIndex, setSlashIndex] = useState(0);
  const [slashDismissed, setSlashDismissed] = useState(false);
  const [dictationPref, setDictationPref] = useState<DictationLang>('he');
  const [attachOpen, setAttachOpen] = useState(false);
  const [composerFocused, setComposerFocused] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const speechRelayRef = useRef<HTMLIFrameElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const dictationBaseRef = useRef('');
  const stopDictationRef = useRef<() => void>(() => {});
  const sessionRef = useRef(sessionName);
  const valueRef = useRef(value);
  sessionRef.current = sessionName;
  valueRef.current = value;

  const isSteering = showStop;
  const hasAttachContext =
    elements.length > 0 || attachments.length > 0 || annotating || recording || recordingPending;
  const showAttachToolbar = attachOpen || composerFocused || hasAttachContext;

  const speechLang = useMemo(
    () => speechLocaleFromPreference(dictationPref),
    [dictationPref],
  );

  const appendTranscript = useCallback((spoken: string) => {
    const base = dictationBaseRef.current.trim();
    const combined = [base, spoken.trim()].filter(Boolean).join(' ');
    setValue((prev) => (prev === combined ? prev : combined));
  }, []);

  const speech = useSpeechRelay({
    iframeRef: speechRelayRef,
    lang: speechLang,
    onTranscript: appendTranscript,
  });

  stopDictationRef.current = speech.stop;

  // Load per-session state only when sessionName changes (never on every keystroke).
  useEffect(() => {
    let cancelled = false;

    void loadDraft(sessionName).then((draft) => {
      if (!cancelled) setValue(draft);
    });
    void loadComposerContext(sessionName).then((c) => {
      if (!cancelled) {
        setElements(c.elements);
        setAttachments(c.attachments);
      }
    });
    void loadMode(sessionName).then((m) => {
      if (!cancelled) setMode(m);
    });
    void loadModel(sessionName).then((m) => {
      if (!cancelled) setModel(m);
    });
    void loadClaudeAgent(sessionName).then((a) => {
      if (!cancelled) setClaudeAgent(a);
    });
    void loadBrowseBackend().then((b) => {
      if (!cancelled) setBrowseBackend(b);
    });
    setAnnotating(false);

    return () => {
      cancelled = true;
      stopDictationRef.current();
      void saveDraft(sessionRef.current, valueRef.current).catch(() => {});
      void chrome.runtime.sendMessage({ kind: 'stop_annotate_mode' }).catch(() => {});
    };
  }, [sessionName]);

  useEffect(() => {
    if (sessionModel === undefined) return;
    setModel(sessionModel ?? null);
    saveModel(sessionName, sessionModel ?? null).catch(() => {});
  }, [sessionName, sessionModel]);

  useEffect(() => {
    if (sessionClaudeAgent === undefined) return;
    setClaudeAgent(sessionClaudeAgent ?? null);
    saveClaudeAgent(sessionName, sessionClaudeAgent ?? null).catch(() => {});
  }, [sessionName, sessionClaudeAgent]);

  // Fetch custom slash commands once.
  useEffect(() => {
    fetchCommands().then(setCommands).catch(() => {});
  }, []);

  useEffect(() => {
    loadDictationPrefs()
      .then((prefs) => setDictationPref(prefs.lang))
      .catch(() => {});
    const onStorage = (
      changes: Record<string, chrome.storage.StorageChange>,
      area: string,
    ) => {
      if (area !== 'local' || !changes.dictationPrefs) return;
      const next = changes.dictationPrefs.newValue as { lang?: string } | undefined;
      if (next?.lang === 'he' || next?.lang === 'en') setDictationPref(next.lang);
    };
    chrome.storage.onChanged.addListener(onStorage);
    return () => chrome.storage.onChanged.removeListener(onStorage);
  }, []);

  // Persist drafts (debounced — avoid storage churn while typing).
  useEffect(() => {
    const id = window.setTimeout(() => {
      saveDraft(sessionName, value).catch(() => {});
    }, 400);
    return () => clearTimeout(id);
  }, [sessionName, value]);
  useEffect(() => {
    saveComposerContext(sessionName, { elements, attachments }).catch(() => {});
  }, [sessionName, elements, attachments]);

  const changeBrowseBackend = useCallback((b: BrowseBackend) => {
    setBrowseBackend(b);
    saveBrowseBackend(b).catch(() => {});
  }, []);

  const changeMode = useCallback(
    (m: AgentMode) => {
      setMode(m);
      saveMode(sessionRef.current, m).catch(() => {});
    },
    [],
  );

  const changeModel = useCallback((modelId: string | null) => {
    setModel(modelId);
    saveModel(sessionRef.current, modelId).catch(() => {});
    setSessionModel(sessionRef.current, modelId).catch((err) => {
      console.warn('[DevScope] setSessionModel failed:', err);
    });
  }, []);

  const changeClaudeAgent = useCallback((slug: string | null) => {
    setClaudeAgent(slug);
    saveClaudeAgent(sessionRef.current, slug).catch(() => {});
    setSessionClaudeAgent(sessionRef.current, slug).catch((err) => {
      console.warn('[DevScope] setSessionClaudeAgent failed:', err);
    });
  }, []);

  const clearAll = useCallback(() => {
    setValue('');
    setElements([]);
    setAttachments([]);
    saveDraft(sessionRef.current, '').catch(() => {});
    if (textareaRef.current) textareaRef.current.style.height = 'auto';
    void chrome.runtime.sendMessage({ kind: 'stop_annotate_mode' }).catch(() => {});
    setAnnotating(false);
  }, []);

  const hasContext = elements.length > 0 || attachments.length > 0;

  const handleSend = useCallback(() => {
    if (speech.isListening) stopDictationRef.current();
    const text = value.trim();
    if (disabled || (!text && !hasContext)) return;
    const context: MessageContext | undefined = hasContext
      ? { elements, attachments }
      : undefined;
    onSend(sessionRef.current, text, {
      context,
      mode,
      model: model ?? undefined,
    });
    clearAll();
    dictationBaseRef.current = '';
  }, [value, disabled, hasContext, elements, attachments, mode, model, onSend, clearAll, speech]);

  const handleToggleDictation = useCallback(() => {
    if (!speech.isSupported || disabled) return;
    if (speech.isListening) {
      stopDictationRef.current();
      return;
    }
    if (isTtsPlaying()) return;

    const dictationLang = resolveSpeechLocale(valueRef.current, dictationPref);
    dictationBaseRef.current = valueRef.current;
    speech.start(dictationLang);
  }, [speech.isSupported, speech.isListening, speech.start, disabled, dictationPref]);

  const toggleDictationLang = useCallback(() => {
    const next: DictationLang = dictationPref === 'he' ? 'en' : 'he';
    setDictationPref(next);
    saveDictationPrefs({ lang: next }).catch(() => {});
  }, [dictationPref]);

  const sendQuickChoice = useCallback(
    (replyText: string) => {
      if (disabled || !replyText.trim()) return;
      onSend(sessionRef.current, replyText.trim(), { mode, model: model ?? undefined });
      clearAll();
    },
    [disabled, mode, model, onSend, clearAll],
  );

  const quickChoices =
    !hideQuickReplies && !value.trim() && !showStop && !disabled
      ? quickRepliesFromMessages(messages)
      : [];

  // Staged annotations from on-page annotate mode.
  useEffect(() => {
    const onMessage = (msg: { kind?: string; element?: ElementContext }) => {
      if (msg?.kind === 'annotation_staged' && msg.element?.selector) {
        setElements((prev) => [...prev, msg.element as ElementContext]);
      }
      if (msg?.kind === 'annotate_mode_ended') {
        setAnnotating(false);
      }
    };
    chrome.runtime.onMessage.addListener(onMessage);
    return () => chrome.runtime.onMessage.removeListener(onMessage);
  }, []);

  const stopAnnotating = useCallback(async () => {
    setAnnotating(false);
    setPickHint('');
    await chrome.runtime.sendMessage({ kind: 'stop_annotate_mode' }).catch(() => {});
  }, []);

  const startAnnotating = useCallback(async () => {
    setPickHint('');
    setAnnotating(true);
    try {
      const res = (await chrome.runtime.sendMessage({
        kind: 'start_annotate_mode',
        sessionName: sessionRef.current,
      })) as {
        ok?: boolean;
        error?: string;
      };
      if (res && res.ok === false) {
        setAnnotating(false);
        const restricted = /restricted|No active tab/i.test(res.error ?? '');
        setPickHint(
          restricted
            ? "Can't inspect this page — open a normal website (chrome:// pages are blocked)."
            : res.error || "Couldn't start annotate mode.",
        );
        setTimeout(() => setPickHint(''), 6000);
      } else if (res?.ok !== false) {
        const data = (res as { data?: { tabTitle?: string } }).data;
        const title = data?.tabTitle;
        setPickHint(
          title
            ? `Orange banner should appear on "${title.slice(0, 40)}" — click elements there`
            : 'Orange banner at top of the page tab — click elements there',
        );
      }
    } catch {
      setAnnotating(false);
      setPickHint("Couldn't reach the page to pick elements.");
      setTimeout(() => setPickHint(''), 6000);
    }
  }, []);

  const runAttach = useCallback(async (kind: PageAttachmentKind) => {
    const action = ATTACH_ACTIONS.find((a) => a.kind === kind);
    if (!action || disabled) return;
    setPickHint(`Capturing ${action.label.toLowerCase()}…`);
    try {
      const res = (await Promise.race([
        chrome.runtime.sendMessage({
          kind: 'execute_browser_tool',
          tool: action.tool,
          args: {},
          sessionName: sessionRef.current,
        }),
        new Promise<never>((_, reject) =>
          setTimeout(() => reject(new Error('Capture timed out — click the page tab and retry')), 28_000),
        ),
      ])) as { ok?: boolean; data?: unknown; error?: string };
      if (res?.ok) {
        setAttachments((prev) => [...prev, toAttachment(kind, res.data)]);
        setPickHint('');
      } else {
        setPickHint(res?.error ?? `Could not capture ${action.label.toLowerCase()}`);
        setTimeout(() => setPickHint(''), 6000);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setPickHint(msg || 'Capture failed');
      setTimeout(() => setPickHint(''), 6000);
    }
  }, [disabled]);

  const addImageFiles = useCallback(async (files: File[]) => {
    if (disabled || files.length === 0) return;
    setPickHint(`Attaching ${files.length === 1 ? 'image' : `${files.length} images`}…`);
    const built = await Promise.all(files.map(fileToImageAttachment));
    const valid = built.filter((a): a is NonNullable<typeof a> => a !== null);
    if (valid.length === 0) {
      setPickHint('Could not read that image.');
      setTimeout(() => setPickHint(''), 5000);
      return;
    }
    setAttachments((prev) => [...prev, ...valid]);
    setPickHint('');
  }, [disabled]);

  const handlePaste = useCallback((e: ClipboardEvent<HTMLTextAreaElement>) => {
    const images = imageFilesFromDataTransfer(e.clipboardData);
    if (images.length > 0) {
      e.preventDefault();
      void addImageFiles(images);
    }
  }, [addImageFiles]);

  const onPickImageClick = useCallback(() => fileInputRef.current?.click(), []);

  const onFileInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = Array.from(e.target.files ?? []);
      void addImageFiles(files);
      e.target.value = ''; // allow re-selecting the same file
    },
    [addImageFiles],
  );

  // ─── Slash command menu ────────────────────────────────────────────────────
  const slashMatch = /^\/(\S*)$/.exec(value);
  const slashQuery = slashMatch ? slashMatch[1].toLowerCase() : null;
  const slashItems: SlashCommand[] =
    slashQuery === null
      ? []
      : [...NATIVE_COMMANDS, ...commands].filter((c) => {
          // Consumer product mode hides dev-workflow commands; Pro shows all.
          if (uiPrefs.productMode === 'consumer' && c.advanced_only) return false;
          if (c.name.slice(1).toLowerCase().startsWith(slashQuery)) return true;
          return (c.aliases ?? []).some((a) => a.slice(1).toLowerCase().startsWith(slashQuery));
        });
  const slashOpen = slashItems.length > 0 && !slashDismissed;

  useEffect(() => {
    setSlashIndex(0);
  }, [slashQuery]);

  const selectCommand = useCallback(
    (cmd: SlashCommand) => {
      // Disabled commands (terminal-only stubs) are never sendable.
      if (isDisabledCommand(cmd)) {
        setValue('');
        setSlashDismissed(true);
        return;
      }

      if (isNativeCommand(cmd)) {
        setValue('');
        setSlashDismissed(true);
        if (cmd.action === 'mode' && cmd.arg) changeMode(cmd.arg as AgentMode);
        else if (cmd.action === 'pick') void startAnnotating();
        else if (cmd.action === 'attach' && cmd.arg) void runAttach(cmd.arg as PageAttachmentKind);
        else if (cmd.action === 'help') onOpenGlossary();
        else if (cmd.action === 'reset') onReset(sessionRef.current);
        else if (cmd.action === 'export') downloadChatMarkdown(sessionRef.current, messages);
        else if (cmd.action === 'clear') {
          setElements([]);
          setAttachments([]);
        }
        return;
      }

      // Bridge builtin commands that take no argument (e.g. /usage, /memory, /new)
      // are sent immediately without requiring the user to press enter.
      // Commands that benefit from an argument (e.g. /compact, /model, /ask)
      // are pre-filled in the textarea so the user can type the argument.
      const NO_ARG_BUILTINS = new Set([
        '/usage',
        '/cost',
        '/context',
        '/memory',
        '/new',
        '/status',
        '/model',
        '/medic',
        '/interrupt',
      ]);
      if (cmd.source === 'builtin' && NO_ARG_BUILTINS.has(cmd.name)) {
        setValue('');
        setSlashDismissed(true);
        onSend(sessionRef.current, cmd.name, { mode });
        return;
      }

      setValue(`${cmd.name} `);
      setSlashDismissed(true);
      textareaRef.current?.focus();
    },
    [changeMode, startAnnotating, runAttach, onOpenGlossary, onSend, onReset, mode, messages],
  );

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      if (slashOpen) {
        if (e.key === 'ArrowDown') {
          e.preventDefault();
          // Skip over disabled commands when navigating down.
          setSlashIndex((i) => {
            let next = (i + 1) % slashItems.length;
            let guard = 0;
            while (slashItems[next]?.disabled && guard < slashItems.length) {
              next = (next + 1) % slashItems.length;
              guard++;
            }
            return next;
          });
          return;
        }
        if (e.key === 'ArrowUp') {
          e.preventDefault();
          // Skip over disabled commands when navigating up.
          setSlashIndex((i) => {
            let prev = (i - 1 + slashItems.length) % slashItems.length;
            let guard = 0;
            while (slashItems[prev]?.disabled && guard < slashItems.length) {
              prev = (prev - 1 + slashItems.length) % slashItems.length;
              guard++;
            }
            return prev;
          });
          return;
        }
        if (e.key === 'Enter') {
          e.preventDefault();
          const cmd = slashItems[slashIndex];
          if (cmd && !cmd.disabled) selectCommand(cmd);
          return;
        }
        if (e.key === 'Escape') {
          e.preventDefault();
          setSlashDismissed(true);
          return;
        }
      }
      const isMod = e.metaKey || e.ctrlKey;
      if ((e.key === 'Enter' && isMod) || (e.key === 'Enter' && !e.shiftKey)) {
        e.preventDefault();
        handleSend();
      }
    },
    [slashOpen, slashItems, slashIndex, selectCommand, handleSend],
  );

  const canSend = !disabled && (value.trim().length > 0 || hasContext);
  const showMic = speech.isSupported;
  const micDisabled = disabled || isTtsPlaying();
  const dictationHint =
    speech.status === 'denied'
      ? 'מיקרופון חסום — פתח Settings → Enable microphone, אשר, ונסה שוב.'
      : speech.status === 'unsupported'
        ? 'קלט קולי לא נתמך בדפדפן הזה.'
        : speech.status === 'error'
          ? speech.lastError === 'network'
            ? 'שירות הדיבור לא זמין — בדוק חיבור אינטרנט.'
            : speech.lastError === 'relay_not_ready'
              ? 'ממתין לשירות קול… נסה שוב בעוד שנייה.'
              : `שגיאת מיקרופון (${speech.lastError || 'error'}) — נסה שוב.`
          : isTtsPlaying()
            ? 'עצור Listen לפני שימוש במיקרופון.'
            : speech.isListening
              ? 'מאזין… דבר עכשיו — הטקסט יופיע בתיבה.'
              : null;

  return (
    <div className="relative z-30 min-w-0 shrink-0 overflow-x-hidden border-t border-line bg-surface-raised px-3 pb-2 pt-1">
      {(elements.length > 0 || attachments.length > 0 || annotating) && (
        <ContextChips
          elements={elements}
          attachments={attachments}
          annotating={annotating}
          onRemoveElement={(i) => setElements((p) => p.filter((_, idx) => idx !== i))}
          onRemoveAttachment={(i) => setAttachments((p) => p.filter((_, idx) => idx !== i))}
          onStopAnnotating={() => void stopAnnotating()}
        />
      )}

      <div className="flex items-center gap-1 pb-1">
        <button
          type="button"
          onClick={() => setAttachOpen((v) => !v)}
          title={showAttachToolbar ? 'Hide attach tools' : 'Attach screenshot, page tools, record…'}
          className={`flex items-center gap-1 rounded-sm border px-1.5 py-0.5 text-2xs transition-colors duration-fast ease-tool ${
            showAttachToolbar
              ? 'border-signal/40 bg-signal-subtle text-signal'
              : 'border-line text-fg-muted hover:border-signal/40 hover:bg-signal-subtle hover:text-signal'
          }`}
        >
          <Paperclip size={11} strokeWidth={2} />
          Attach
        </button>
        {recording && (
          <span className="flex items-center gap-1 text-2xs text-danger">
            <span className="h-1.5 w-1.5 rounded-full bg-danger animate-cursor-pulse" aria-hidden />
            Rec {recElapsed}
          </span>
        )}
      </div>

      {/* Attach toolbar — collapsed by default; opens via Attach pill or composer focus */}
      <div
        className="overflow-hidden transition-[max-height,opacity] duration-fast ease-tool"
        style={{ maxHeight: showAttachToolbar ? 120 : 0, opacity: showAttachToolbar ? 1 : 0 }}
      >
        <div className="flex flex-wrap gap-1 pb-1.5">
          <ToolbarButton
            label={annotating ? 'Picking…' : 'Pick element'}
            icon={Crosshair}
            disabled={disabled || annotating}
            onClick={() => void startAnnotating()}
          />
          {ATTACH_ACTIONS.map((a) => (
            <ToolbarButton
              key={a.kind}
              label={a.label}
              icon={a.icon}
              disabled={disabled || annotating}
              onClick={() => void runAttach(a.kind)}
            />
          ))}
          <ToolbarButton
            label="Image"
            icon={ImageIcon}
            disabled={disabled}
            onClick={onPickImageClick}
          />
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            multiple
            className="hidden"
            onChange={onFileInputChange}
          />
          <button
            type="button"
            disabled={recordingPending}
            onMouseDown={(e) => e.preventDefault()}
            onClick={onToggleRecording}
            title={recording ? 'Stop recording' : 'Record this tab'}
            className={`flex items-center gap-1 rounded-sm border px-1.5 py-1 text-2xs transition-colors duration-fast ease-tool ${
              recording || recordingPending
                ? 'border-danger/50 bg-danger-subtle text-danger'
                : 'border-line text-fg-muted hover:border-signal/40 hover:bg-signal-subtle hover:text-signal'
            }`}
          >
            {recording || recordingPending ? (
              <>
                <span className="h-2 w-2 rounded-full bg-danger animate-cursor-pulse" aria-hidden />
                {recording ? recElapsed : 'Starting…'}
              </>
            ) : (
              <>
                <Video size={12} strokeWidth={2} />
                Record
              </>
            )}
          </button>
        </div>
      </div>

      {annotating && (
        <div className="space-y-0.5 pb-1">
          <div className="flex items-center gap-1.5 text-2xs text-signal">
            <Crosshair size={11} strokeWidth={2.25} />
            Click elements on the page · Esc when done
          </div>
          {pickHint && <p className="text-2xs text-fg-muted">{pickHint}</p>}
        </div>
      )}

      {pickHint && !annotating && (
        <div className="pb-1 text-2xs text-warning">{pickHint}</div>
      )}

      {recordingError && (
        <div className="pb-1 text-2xs text-danger">{recordingError}</div>
      )}

      {quickChoices.length > 0 && (
        <QuickChoiceBar
          choices={quickChoices}
          disabled={disabled}
          onPick={sendQuickChoice}
        />
      )}

      <div className="relative">
        {slashOpen && <SlashMenu items={slashItems} activeIndex={slashIndex} onSelect={selectCommand} />}
        <textarea
          ref={textareaRef}
          value={value}
          onFocus={() => setComposerFocused(true)}
          onBlur={() => {
            window.setTimeout(() => setComposerFocused(false), 120);
          }}
          onChange={(e) => {
            if (speech.isListening) stopDictationRef.current();
            setValue(e.target.value);
            setSlashDismissed(false);
          }}
          onKeyDown={handleKeyDown}
          onPaste={handlePaste}
          disabled={disabled}
          maxLength={MAX_CHARS}
          placeholder={
            elements.length > 0
              ? 'Add a global instruction for all annotations… (optional)'
              : 'Message…  (/ for commands)'
          }
          rows={2}
          dir="auto"
          className="max-h-32 min-h-[2.25rem] w-full resize-none overflow-y-auto rounded-md border border-line bg-surface px-3 py-1.5 text-sm leading-[1.5] text-fg placeholder-fg-subtle outline-none focus:border-signal focus:bg-surface-overlay"
          aria-label="Message"
        />
        <div className="min-w-0 pt-1.5">
          <div className="flex min-w-0 flex-wrap items-center gap-1.5">
            <BoundTabPill sessionName={sessionName} onBoundChange={onBoundTabChange} />
            <ModePill mode={mode} onChange={changeMode} />
            {(agent === 'claude' || agent === 'cursor') && (
              <ModelPill modelId={model} agent={agent} onChange={changeModel} />
            )}
            {agent === 'claude' && (
              <SubagentPill agentSlug={claudeAgent} onChange={changeClaudeAgent} />
            )}
            <BrowseBackendPill backend={browseBackend} onChange={changeBrowseBackend} />
          </div>
          {dictationHint && (
            <p className="mt-1 text-2xs text-fg-muted">{dictationHint}</p>
          )}
          <div className="mt-1.5 flex items-center justify-end gap-2">
            <span className="min-w-[4.5rem] text-right font-mono text-2xs tabular-nums text-fg-subtle">
              {value.length}/{MAX_CHARS}
            </span>
            {showMic && (
              <>
              <button
                type="button"
                onClick={toggleDictationLang}
                disabled={micDisabled || speech.isListening}
                title={
                  dictationPref === 'he'
                    ? 'שפת דיקטיון: עברית — לחץ למעבר לאנגלית'
                    : 'Dictation language: English — click for Hebrew'
                }
                aria-label={
                  dictationPref === 'he' ? 'Dictation language Hebrew' : 'Dictation language English'
                }
                className="flex h-9 min-w-[2.25rem] shrink-0 items-center justify-center rounded-md border border-line px-1.5 text-2xs font-medium text-fg-muted transition-colors duration-fast ease-tool hover:border-signal/40 hover:bg-signal-subtle hover:text-signal disabled:opacity-40"
              >
                {dictationPref === 'he' ? 'עב' : 'EN'}
              </button>
              <button
                type="button"
                onClick={handleToggleDictation}
                disabled={micDisabled}
                title={speech.isListening ? 'Stop dictation' : 'Dictate message'}
                aria-label={speech.isListening ? 'Stop dictation' : 'Dictate message'}
                aria-pressed={speech.isListening}
                className={`relative flex h-9 w-9 shrink-0 items-center justify-center rounded-md border transition-colors duration-fast ease-tool disabled:opacity-40 ${
                  speech.isListening
                    ? 'border-danger/50 bg-danger-subtle text-danger'
                    : 'border-line text-fg-muted hover:border-signal/40 hover:bg-signal-subtle hover:text-signal'
                }`}
              >
                {speech.isListening ? (
                  <>
                    <MicOff size={16} strokeWidth={2} />
                    <span
                      className="absolute right-1 top-1 h-1.5 w-1.5 rounded-full bg-danger animate-cursor-pulse"
                      aria-hidden
                    />
                  </>
                ) : (
                  <Mic size={16} strokeWidth={2} />
                )}
              </button>
              </>
            )}
            <button
              onClick={handleSend}
              disabled={!canSend}
              aria-label={isSteering ? 'Send steering message' : 'Send'}
              className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-md transition-colors duration-fast ease-tool disabled:opacity-40 ${
                isSteering
                  ? 'border border-signal text-signal hover:bg-signal-subtle'
                  : 'bg-signal text-signal-contrast hover:bg-signal-hover'
              }`}
            >
              {isSteering ? <CornerDownLeft size={16} strokeWidth={2.25} /> : <Send size={16} strokeWidth={2.25} />}
            </button>
          </div>
        </div>
      </div>
      {/* Hidden iframe — Chrome allows mic only here (allow="microphone"), not in the panel document. */}
      <iframe
        ref={speechRelayRef}
        src={speech.relayUrl}
        title="DevScope speech relay"
        allow="microphone"
        className="pointer-events-none absolute h-px w-px opacity-0"
        aria-hidden
      />
    </div>
  );
}

function ToolbarButton({
  label,
  icon: Icon,
  disabled,
  onClick,
}: {
  label: string;
  icon: typeof Crosshair;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      title={label}
      onMouseDown={(e) => e.preventDefault()}
      onClick={onClick}
      className="flex items-center gap-1 rounded-sm border border-line px-1.5 py-1 text-2xs text-fg-muted transition-colors duration-fast ease-tool hover:border-signal/40 hover:bg-signal-subtle hover:text-signal disabled:opacity-40"
    >
      <Icon size={12} strokeWidth={2} />
      {label}
    </button>
  );
}
