/**
 * storage.ts — typed wrappers around chrome.storage.local for session data.
 *
 * Chat message lists are cached here per Chrome profile for fast reopen.
 * The authoritative conversation record is the bridge JSONL transcript (shared
 * across profiles); see historyLoader.ts for merge on load.
 */
import type { ChatMessage } from '../store/sessionStore';
import type { AgentMode, Agent, ElementContext, PageAttachment } from '@/shared/frames';
import type { BrowseBackend } from '@/shared/browseBackend';
import { safeLocalSet } from '@/shared/storageWrite';

const HISTORY_KEY_PREFIX = 'session.history.';
const DRAFT_KEY_PREFIX = 'session.draft.';
const CONTEXT_KEY_PREFIX = 'session.context.';
const MODE_KEY_PREFIX = 'session.mode.';
const MODEL_KEY_PREFIX = 'session.model.';
const CLAUDE_AGENT_KEY_PREFIX = 'session.claude_agent.';
const BROWSE_BACKEND_KEY = 'browseBackend';
const PROJECT_PATHS_KEY = 'projectPaths';
const MAX_HISTORY = 100;

/** Drop inlined base64 / huge HTML from a cache row — bridge JSONL is authoritative. */
function slimMessageForCache(msg: ChatMessage): ChatMessage {
  if (!msg.context) return msg;
  const elements = (msg.context.elements ?? []).map((el) => ({
    ...el,
    outerHTML:
      el.outerHTML && el.outerHTML.length > 400
        ? `${el.outerHTML.slice(0, 400)}…`
        : el.outerHTML,
    screenshotSnippet: undefined,
  }));
  const attachments = (msg.context.attachments ?? []).map((att) => {
    if (typeof att.data === 'string' && att.data.startsWith('data:')) {
      return { ...att, data: '<inline-omitted>' };
    }
    return att;
  });
  return { ...msg, context: { ...msg.context, elements, attachments } };
}

export interface ComposerContext {
  elements: ElementContext[];
  attachments: PageAttachment[];
}

const EMPTY_CONTEXT: ComposerContext = { elements: [], attachments: [] };

export async function loadHistory(sessionName: string): Promise<ChatMessage[]> {
  const key = HISTORY_KEY_PREFIX + sessionName;
  const result = await chrome.storage.local.get(key);
  return (result[key] as ChatMessage[] | undefined) ?? [];
}

export async function saveHistory(sessionName: string, messages: ChatMessage[]): Promise<void> {
  const key = HISTORY_KEY_PREFIX + sessionName;
  const capped = messages.slice(-MAX_HISTORY).map(slimMessageForCache);
  try {
    await safeLocalSet({ [key]: capped }, { keepSession: sessionName });
  } catch (err) {
    // Cache write must never break chat send / UI updates.
    console.warn('[DevScope] saveHistory failed:', err);
  }
}

export async function clearHistory(sessionName: string): Promise<void> {
  const key = HISTORY_KEY_PREFIX + sessionName;
  await chrome.storage.local.remove(key);
}

export async function loadDraft(sessionName: string): Promise<string> {
  const key = DRAFT_KEY_PREFIX + sessionName;
  const result = await chrome.storage.local.get(key);
  return (result[key] as string | undefined) ?? '';
}

export async function saveDraft(sessionName: string, text: string): Promise<void> {
  const key = DRAFT_KEY_PREFIX + sessionName;
  if (text) {
    try {
      await safeLocalSet({ [key]: text }, { keepSession: sessionName });
    } catch (err) {
      console.warn('[DevScope] saveDraft failed:', err);
    }
  } else {
    await chrome.storage.local.remove(key);
  }
}

export async function loadComposerContext(sessionName: string): Promise<ComposerContext> {
  const key = CONTEXT_KEY_PREFIX + sessionName;
  const result = await chrome.storage.local.get(key);
  return (result[key] as ComposerContext | undefined) ?? { ...EMPTY_CONTEXT };
}

export async function saveComposerContext(sessionName: string, ctx: ComposerContext): Promise<void> {
  const key = CONTEXT_KEY_PREFIX + sessionName;
  if (ctx.elements.length === 0 && ctx.attachments.length === 0) {
    await chrome.storage.local.remove(key);
  } else {
    try {
      // Never persist inlined screenshots/base64 in the composer cache.
      const attachments = ctx.attachments.map((att) =>
        typeof att.data === 'string' && att.data.startsWith('data:')
          ? { ...att, data: '<inline-omitted>' }
          : att,
      );
      await safeLocalSet({ [key]: { ...ctx, attachments } }, { keepSession: sessionName });
    } catch (err) {
      console.warn('[DevScope] saveComposerContext failed:', err);
    }
  }
}

export async function loadMode(sessionName: string): Promise<AgentMode> {
  const key = MODE_KEY_PREFIX + sessionName;
  const result = await chrome.storage.local.get(key);
  return (result[key] as AgentMode | undefined) ?? 'act';
}

export async function saveMode(sessionName: string, mode: AgentMode): Promise<void> {
  const key = MODE_KEY_PREFIX + sessionName;
  await chrome.storage.local.set({ [key]: mode });
}

/** Per-session Claude model id, or null for CLI default. */
export async function loadModel(sessionName: string): Promise<string | null> {
  const key = MODEL_KEY_PREFIX + sessionName;
  const result = await chrome.storage.local.get(key);
  const raw = result[key];
  if (raw === null || raw === undefined) return null;
  return String(raw);
}

export async function saveModel(sessionName: string, modelId: string | null): Promise<void> {
  const key = MODEL_KEY_PREFIX + sessionName;
  if (modelId) {
    await chrome.storage.local.set({ [key]: modelId });
  } else {
    await chrome.storage.local.remove(key);
  }
}

/** Per-session Claude subagent slug (--agent), or null for default. */
export async function loadClaudeAgent(sessionName: string): Promise<string | null> {
  const key = CLAUDE_AGENT_KEY_PREFIX + sessionName;
  const result = await chrome.storage.local.get(key);
  const raw = result[key];
  if (raw === null || raw === undefined) return null;
  return String(raw);
}

export async function saveClaudeAgent(sessionName: string, slug: string | null): Promise<void> {
  const key = CLAUDE_AGENT_KEY_PREFIX + sessionName;
  if (slug) {
    await chrome.storage.local.set({ [key]: slug });
  } else {
    await chrome.storage.local.remove(key);
  }
}

export async function loadBrowseBackend(): Promise<BrowseBackend> {
  const result = await chrome.storage.local.get(BROWSE_BACKEND_KEY);
  const v = result[BROWSE_BACKEND_KEY] as BrowseBackend | undefined;
  if (v === 'extension' || v === 'cdp' || v === 'auto') return v;
  return 'auto';
}

export async function saveBrowseBackend(backend: BrowseBackend): Promise<void> {
  await chrome.storage.local.set({ [BROWSE_BACKEND_KEY]: backend });
}

export async function loadProjectPaths(): Promise<string[]> {
  const result = await chrome.storage.local.get(PROJECT_PATHS_KEY);
  return (result[PROJECT_PATHS_KEY] as string[] | undefined) ?? [];
}

export async function saveProjectPaths(paths: string[]): Promise<void> {
  await chrome.storage.local.set({ [PROJECT_PATHS_KEY]: paths });
}

// ─── English Coach prefs ─────────────────────────────────────────────────────

const COACH_PREFS_KEY = 'coachPrefs';

export type CoachFocus = 'vocabulary' | 'grammar' | 'spelling' | 'sentences';
export const ALL_COACH_FOCUS: CoachFocus[] = ['vocabulary', 'grammar', 'spelling', 'sentences'];

export interface CoachPrefs {
  enabled: boolean;
  lang: string;
  focus: CoachFocus[];
}

const DEFAULT_COACH_PREFS: CoachPrefs = { enabled: false, lang: 'he', focus: ALL_COACH_FOCUS };

export async function loadCoachPrefs(): Promise<CoachPrefs> {
  const result = await chrome.storage.local.get(COACH_PREFS_KEY);
  const stored = result[COACH_PREFS_KEY] as Partial<CoachPrefs> | undefined;
  if (!stored) return { ...DEFAULT_COACH_PREFS };
  const focus = Array.isArray(stored.focus) && stored.focus.length > 0
    ? (stored.focus as CoachFocus[])
    : DEFAULT_COACH_PREFS.focus;
  return {
    enabled: typeof stored.enabled === 'boolean' ? stored.enabled : DEFAULT_COACH_PREFS.enabled,
    lang: typeof stored.lang === 'string' && stored.lang ? stored.lang : DEFAULT_COACH_PREFS.lang,
    focus,
  };
}

export async function saveCoachPrefs(prefs: CoachPrefs): Promise<void> {
  await chrome.storage.local.set({ [COACH_PREFS_KEY]: prefs });
}

// ─── Attention alert prefs ───────────────────────────────────────────────────

const ATTENTION_PREFS_KEY = 'attentionPrefs';

export interface AttentionPrefs {
  enabled: boolean;
  sound: boolean;
  flashTitle: boolean;
  desktopNotification: boolean;
  /** Sound/notify even when the active session is open in the side panel. */
  alertWhenActive: boolean;
}

const DEFAULT_ATTENTION_PREFS: AttentionPrefs = {
  enabled: true,
  sound: true,
  flashTitle: true,
  desktopNotification: true,
  alertWhenActive: false,
};

export async function loadAttentionPrefs(): Promise<AttentionPrefs> {
  const result = await chrome.storage.local.get(ATTENTION_PREFS_KEY);
  const stored = result[ATTENTION_PREFS_KEY] as Partial<AttentionPrefs> | undefined;
  if (!stored) return { ...DEFAULT_ATTENTION_PREFS };
  return {
    enabled: typeof stored.enabled === 'boolean' ? stored.enabled : DEFAULT_ATTENTION_PREFS.enabled,
    sound: typeof stored.sound === 'boolean' ? stored.sound : DEFAULT_ATTENTION_PREFS.sound,
    flashTitle:
      typeof stored.flashTitle === 'boolean' ? stored.flashTitle : DEFAULT_ATTENTION_PREFS.flashTitle,
    desktopNotification:
      typeof stored.desktopNotification === 'boolean'
        ? stored.desktopNotification
        : DEFAULT_ATTENTION_PREFS.desktopNotification,
    alertWhenActive:
      typeof stored.alertWhenActive === 'boolean'
        ? stored.alertWhenActive
        : DEFAULT_ATTENTION_PREFS.alertWhenActive,
  };
}

export async function saveAttentionPrefs(prefs: AttentionPrefs): Promise<void> {
  await chrome.storage.local.set({ [ATTENTION_PREFS_KEY]: prefs });
}

// ─── Dictation (STT) language ────────────────────────────────────────────────

const DICTATION_PREFS_KEY = 'dictationPrefs';

export type DictationLang = 'he' | 'en';

export interface DictationPrefs {
  lang: DictationLang;
}

const DEFAULT_DICTATION_PREFS: DictationPrefs = { lang: 'he' };

export async function loadDictationPrefs(): Promise<DictationPrefs> {
  const result = await chrome.storage.local.get(DICTATION_PREFS_KEY);
  const stored = result[DICTATION_PREFS_KEY] as Partial<DictationPrefs> | undefined;
  if (!stored) return { ...DEFAULT_DICTATION_PREFS };
  const lang = stored.lang === 'en' ? 'en' : 'he';
  return { lang };
}

export async function saveDictationPrefs(prefs: DictationPrefs): Promise<void> {
  await chrome.storage.local.set({ [DICTATION_PREFS_KEY]: prefs });
}

// ─── Context / auto-compact ────────────────────────────────────────────────────

const CONTEXT_PREFS_KEY = 'contextPrefs';

export interface ContextPrefs {
  /** Summarize transcript after every N user messages (0 = off). */
  autoCompactEvery: number;
  /** Bind the focused browser tab when none is set. */
  autoBindFocusedTab: boolean;
}

const DEFAULT_CONTEXT_PREFS: ContextPrefs = {
  autoCompactEvery: 0,
  autoBindFocusedTab: false,
};

export async function loadContextPrefs(): Promise<ContextPrefs> {
  const result = await chrome.storage.local.get(CONTEXT_PREFS_KEY);
  const stored = result[CONTEXT_PREFS_KEY] as Partial<ContextPrefs> | undefined;
  if (!stored) return { ...DEFAULT_CONTEXT_PREFS };
  const every = Number(stored.autoCompactEvery);
  return {
    autoCompactEvery:
      Number.isFinite(every) && every >= 0 ? Math.min(50, Math.floor(every)) : DEFAULT_CONTEXT_PREFS.autoCompactEvery,
    autoBindFocusedTab:
      typeof stored.autoBindFocusedTab === 'boolean'
        ? stored.autoBindFocusedTab
        : DEFAULT_CONTEXT_PREFS.autoBindFocusedTab,
  };
}

export async function saveContextPrefs(prefs: ContextPrefs): Promise<void> {
  await chrome.storage.local.set({ [CONTEXT_PREFS_KEY]: prefs });
}

// ─── UI / browser automation prefs ───────────────────────────────────────────

const UI_PREFS_KEY = 'uiPrefs';

/** 'pro' = today's full UI (default); 'consumer' hides advanced slash commands. */
export type ProductMode = 'pro' | 'consumer';

/** 'terminal' = interactive Claude PTY (default); 'stream' = legacy chat bubbles. */
export type InteractionMode = 'terminal' | 'stream';

export interface UiPrefs {
  showClickHighlights: boolean;
  actionSound: boolean;
  productMode: ProductMode;
  interactionMode: InteractionMode;
  /** Live stream diagnostics panel + `[DevScope:stream]` console logs. */
  streamDebug: boolean;
}

const DEFAULT_UI_PREFS: UiPrefs = {
  showClickHighlights: true,
  actionSound: false,
  productMode: 'pro',
  interactionMode: 'stream',
  streamDebug: false,
};

export async function loadUiPrefs(): Promise<UiPrefs> {
  const result = await chrome.storage.local.get(UI_PREFS_KEY);
  const stored = result[UI_PREFS_KEY] as Partial<UiPrefs> | undefined;
  if (!stored) return { ...DEFAULT_UI_PREFS };
  return {
    showClickHighlights:
      typeof stored.showClickHighlights === 'boolean'
        ? stored.showClickHighlights
        : DEFAULT_UI_PREFS.showClickHighlights,
    actionSound:
      typeof stored.actionSound === 'boolean'
        ? stored.actionSound
        : DEFAULT_UI_PREFS.actionSound,
    productMode: stored.productMode === 'consumer' ? 'consumer' : 'pro',
    interactionMode:
      stored.interactionMode === 'terminal' ? 'terminal' : 'stream',
    streamDebug:
      typeof stored.streamDebug === 'boolean'
        ? stored.streamDebug
        : DEFAULT_UI_PREFS.streamDebug,
  };
}

export async function saveUiPrefs(prefs: UiPrefs): Promise<void> {
  await chrome.storage.local.set({ [UI_PREFS_KEY]: prefs });
}

// ─── WhatsApp assist prefs ───────────────────────────────────────────────────

const WA_ASSIST_PREFS_KEY = 'waAssistPrefs';

export interface WaAssistPrefs {
  agent: Agent;
  model: string | null;
  mode: AgentMode;
}

const DEFAULT_WA_ASSIST_PREFS: WaAssistPrefs = {
  agent: 'cursor',
  model: null,
  mode: 'act',
};

export async function loadWaAssistPrefs(): Promise<WaAssistPrefs> {
  const result = await chrome.storage.local.get(WA_ASSIST_PREFS_KEY);
  const stored = result[WA_ASSIST_PREFS_KEY] as Partial<WaAssistPrefs> | undefined;
  if (!stored) return { ...DEFAULT_WA_ASSIST_PREFS };
  const agent = stored.agent === 'claude' ? 'claude' : 'cursor';
  const mode =
    stored.mode === 'plan' || stored.mode === 'inspect' || stored.mode === 'test'
      ? stored.mode
      : 'act';
  return {
    agent,
    model: typeof stored.model === 'string' ? stored.model : null,
    mode,
  };
}

export async function saveWaAssistPrefs(prefs: WaAssistPrefs): Promise<void> {
  await chrome.storage.local.set({ [WA_ASSIST_PREFS_KEY]: prefs });
}
