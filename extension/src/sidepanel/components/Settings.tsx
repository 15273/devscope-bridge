/**
 * Settings — full-panel view: connection (token + test), appearance, paths.
 */
import { useState, useEffect, useCallback, KeyboardEvent } from 'react';
import { AlertCircle, ArrowLeft, Check, ChevronRight, FolderOpen, Loader2, X } from 'lucide-react';
import {
  loadProjectPaths,
  saveProjectPaths,
  loadCoachPrefs,
  saveCoachPrefs,
  loadAttentionPrefs,
  saveAttentionPrefs,
  loadDictationPrefs,
  saveDictationPrefs,
  loadContextPrefs,
  saveContextPrefs,
  loadUiPrefs,
  saveUiPrefs,
  ALL_COACH_FOCUS,
  type AttentionPrefs,
  type CoachFocus,
  type DictationLang,
  type ContextPrefs,
  type InteractionMode,
  type ProductMode,
  type UiPrefs,
} from '../utils/storage';
import { loadBrowseBackend, saveBrowseBackend } from '@/background/browse_backend_storage';
import { BROWSE_BACKENDS, type BrowseBackend } from '@/shared/browseBackend';
import { ensureNotificationPermission } from '../utils/attentionAlerts';
import { openMicGrantPage } from '../utils/speech/micPermission';
import { setCoachLangCache } from './EnglishCoachCard';
import { pingBridge, type BridgeHealth } from '../bridge';
import { FolderPickerModal } from './FolderPickerModal';
import { useTheme } from '../hooks/useTheme';
import type { ThemePref } from '../theme';
import { SetupGuide } from './SetupGuide';
import { CapabilitiesPanel } from './CapabilitiesPanel';
import { OrchestratorSettings } from './OrchestratorSettings';
import { EmployeeSettings } from './EmployeeSettings';
import { PluginStore } from './PluginStore';

interface SettingsProps {
  onClose: () => void;
}

const STORAGE_KEY = 'bridgeToken';
type TestState = 'idle' | 'testing' | BridgeHealth;

export function Settings({ onClose }: SettingsProps) {
  const [token, setToken] = useState('');
  const [tokenSaved, setTokenSaved] = useState(false);
  const [testState, setTestState] = useState<TestState>('idle');
  const [projectPaths, setProjectPaths] = useState<string[]>([]);
  const [newPath, setNewPath] = useState('');
  const [pathError, setPathError] = useState('');
  const [showGuide, setShowGuide] = useState(false);
  const [coachEnabled, setCoachEnabled] = useState(false);
  const [coachLang, setCoachLang] = useState('he');
  const [coachFocus, setCoachFocus] = useState<CoachFocus[]>(ALL_COACH_FOCUS);
  const [dictationLang, setDictationLang] = useState<DictationLang>('he');
  const [contextPrefs, setContextPrefs] = useState<ContextPrefs>({
    autoCompactEvery: 0,
    autoBindFocusedTab: false,
  });
  const [attentionPrefs, setAttentionPrefs] = useState<AttentionPrefs>({
    enabled: true,
    sound: true,
    flashTitle: true,
    desktopNotification: true,
    alertWhenActive: false,
  });
  const [browseBackend, setBrowseBackend] = useState<BrowseBackend>('auto');
  const [uiPrefs, setUiPrefs] = useState<UiPrefs>({
    showClickHighlights: true,
    actionSound: false,
    productMode: 'pro',
    interactionMode: 'terminal',
    streamDebug: false,
  });
  const { pref, setTheme } = useTheme();

  useEffect(() => {
    chrome.storage.local
      .get(STORAGE_KEY)
      .then((result) => {
        const stored = result[STORAGE_KEY] as string | undefined;
        if (stored) setToken(stored);
      })
      .catch(() => {});
    loadProjectPaths().then(setProjectPaths).catch(() => {});
    loadCoachPrefs()
      .then((prefs) => {
        setCoachEnabled(prefs.enabled);
        setCoachLang(prefs.lang);
        setCoachFocus(prefs.focus);
      })
      .catch(() => {});
    loadAttentionPrefs().then(setAttentionPrefs).catch(() => {});
    loadDictationPrefs()
      .then((prefs) => setDictationLang(prefs.lang))
      .catch(() => {});
    loadContextPrefs().then(setContextPrefs).catch(() => {});
    loadBrowseBackend().then(setBrowseBackend).catch(() => {});
    loadUiPrefs().then(setUiPrefs).catch(() => {});
  }, []);

  const patchUiPrefs = useCallback((patch: Partial<UiPrefs>) => {
    setUiPrefs((prev) => {
      const next = { ...prev, ...patch };
      saveUiPrefs(next).catch(() => {});
      return next;
    });
  }, []);

  const handleDictationLangChange = useCallback((lang: DictationLang) => {
    setDictationLang(lang);
    saveDictationPrefs({ lang }).catch(() => {});
  }, []);

  const patchContextPrefs = useCallback((patch: Partial<ContextPrefs>) => {
    setContextPrefs((prev) => {
      const next = { ...prev, ...patch };
      saveContextPrefs(next).catch(() => {});
      return next;
    });
  }, []);

  const handleSaveToken = useCallback(() => {
    const trimmed = token.trim();
    chrome.storage.local
      .set({ [STORAGE_KEY]: trimmed })
      .then(() => {
        chrome.runtime.sendMessage({ kind: 'update_token', token: trimmed }).catch(() => {});
        setTokenSaved(true);
        setTimeout(() => setTokenSaved(false), 2000);
      })
      .catch(() => {});
  }, [token]);

  const handleTest = useCallback(async () => {
    setTestState('testing');
    setTestState(await pingBridge());
  }, []);

  const validatePath = useCallback((val: string): string => {
    if (!val.trim()) return 'Path cannot be empty';
    if (!val.startsWith('/')) return 'Path must be absolute (start with /)';
    return '';
  }, []);

  const handleAddPath = useCallback(() => {
    const err = validatePath(newPath);
    if (err) {
      setPathError(err);
      return;
    }
    const trimmed = newPath.trim();
    if (projectPaths.includes(trimmed)) {
      setPathError('Path already added');
      return;
    }
    const updated = [...projectPaths, trimmed];
    setProjectPaths(updated);
    saveProjectPaths(updated).catch(() => {});
    setNewPath('');
    setPathError('');
  }, [newPath, projectPaths, validatePath]);

  const [pickerOpen, setPickerOpen] = useState(false);

  const handleFolderPicked = useCallback(
    (path: string) => {
      setPickerOpen(false);
      setPathError('');
      if (projectPaths.includes(path)) {
        setPathError('Path already added');
        return;
      }
      const updated = [...projectPaths, path];
      setProjectPaths(updated);
      saveProjectPaths(updated).catch(() => {});
    },
    [projectPaths],
  );

  const handleDeletePath = useCallback(
    (path: string) => {
      const updated = projectPaths.filter((p) => p !== path);
      setProjectPaths(updated);
      saveProjectPaths(updated).catch(() => {});
    },
    [projectPaths],
  );

  const handlePathKeyDown = useCallback(
    (e: KeyboardEvent<HTMLInputElement>) => {
      if (e.key === 'Enter') handleAddPath();
    },
    [handleAddPath],
  );

  const handleCoachEnabledChange = useCallback(
    (enabled: boolean) => {
      setCoachEnabled(enabled);
      saveCoachPrefs({ enabled, lang: coachLang, focus: coachFocus }).catch(() => {});
    },
    [coachLang, coachFocus],
  );

  const handleCoachLangChange = useCallback(
    (lang: string) => {
      setCoachLang(lang);
      setCoachLangCache(lang);
      saveCoachPrefs({ enabled: coachEnabled, lang, focus: coachFocus }).catch(() => {});
    },
    [coachEnabled, coachFocus],
  );

  const handleCoachFocusToggle = useCallback(
    (area: CoachFocus) => {
      setCoachFocus((prev) => {
        const next = prev.includes(area)
          ? prev.filter((f) => f !== area)
          : [...prev, area];
        const effective = next.length > 0 ? next : ALL_COACH_FOCUS;
        saveCoachPrefs({ enabled: coachEnabled, lang: coachLang, focus: effective }).catch(() => {});
        return effective;
      });
    },
    [coachEnabled, coachLang],
  );

  const patchAttentionPrefs = useCallback((patch: Partial<AttentionPrefs>) => {
    setAttentionPrefs((prev) => {
      const next = { ...prev, ...patch };
      saveAttentionPrefs(next).catch(() => {});
      return next;
    });
  }, []);

  const handleDesktopNotificationToggle = useCallback(
    async (enabled: boolean) => {
      if (enabled) {
        const ok = await ensureNotificationPermission();
        if (!ok) return;
      }
      patchAttentionPrefs({ desktopNotification: enabled });
    },
    [patchAttentionPrefs],
  );

  return (
    <div className="flex h-full flex-1 flex-col overflow-y-auto bg-surface">
      <div className="flex items-center gap-2 border-b border-line bg-surface-raised px-3 py-2.5">
        <button
          onClick={onClose}
          aria-label="Back"
          className="rounded-md p-1 text-fg-subtle transition-colors duration-fast ease-tool hover:bg-surface-overlay hover:text-fg"
        >
          <ArrowLeft size={16} strokeWidth={2} />
        </button>
        <span className="text-sm font-semibold text-fg">Settings</span>
      </div>

      <div className="flex flex-col gap-6 px-4 py-4">
        {/* Connection */}
        <section>
          <SectionTitle>Connection</SectionTitle>
          <p className="mb-2 text-xs text-fg-muted">
            Paste the value from{' '}
            <code className="rounded-sm bg-surface-overlay px-1 font-mono text-fg">~/.dev-bridge/token</code>
          </p>
          <input
            type="password"
            value={token}
            onChange={(e) => {
              setToken(e.target.value);
              setTestState('idle');
            }}
            placeholder="Paste token here"
            className="mb-2 w-full rounded-md border border-line bg-surface-overlay px-3 py-2 text-sm text-fg outline-none transition-colors duration-fast ease-tool focus:border-signal"
          />
          <div className="flex items-center gap-2">
            <button
              onClick={handleSaveToken}
              className="rounded-md bg-signal px-4 py-1.5 text-xs font-medium text-signal-contrast transition-colors duration-fast ease-tool hover:bg-signal-hover"
            >
              {tokenSaved ? 'Saved' : 'Save'}
            </button>
            <button
              onClick={handleTest}
              className="rounded-md border border-line px-3 py-1.5 text-xs font-medium text-fg-muted transition-colors duration-fast ease-tool hover:bg-surface-overlay hover:text-fg"
            >
              Test connection
            </button>
            <TestResult state={testState} />
          </div>

          {/* Always-reachable setup guide */}
          <button
            onClick={() => setShowGuide((v) => !v)}
            className="mt-3 flex items-center gap-1 text-xs font-medium text-signal transition-colors duration-fast ease-tool hover:text-signal-hover"
          >
            <ChevronRight
              size={13}
              strokeWidth={2.25}
              className={`transition-transform duration-fast ease-tool ${showGuide ? 'rotate-90' : ''}`}
            />
            How to connect DevScope
          </button>
          {showGuide && (
            <div className="mt-3 rounded-md border border-line bg-surface-raised p-3">
              <SetupGuide />
            </div>
          )}
        </section>

        <CapabilitiesPanel />

        <PluginStore />

        {/* Appearance */}
        <section>
          <SectionTitle>Appearance</SectionTitle>
          <ThemeToggle pref={pref} onChange={setTheme} />
        </section>

        {/* Interaction mode */}
        <section>
          <SectionTitle>Chat engine</SectionTitle>
          <p className="mb-3 text-xs text-fg-muted">
            Terminal (recommended) runs real interactive Claude in the panel — same
            CLI as your shell, with composer attach tools feeding context into the PTY.
            Stream chat (legacy) uses the old bubble UI and bridge stream-json path.
          </p>
          <InteractionModeToggle
            mode={uiPrefs.interactionMode}
            onChange={(m) => patchUiPrefs({ interactionMode: m })}
          />
        </section>

        {/* Product mode */}
        <section>
          <SectionTitle>Product mode</SectionTitle>
          <p className="mb-3 text-xs text-fg-muted">
            Pro shows every slash command and dev tool (today&apos;s behavior). Simple
            hides advanced dev commands and shows a capabilities strip above the composer.
          </p>
          <ProductModeToggle
            mode={uiPrefs.productMode}
            onChange={(m) => patchUiPrefs({ productMode: m })}
          />
        </section>

        {/* Attention alerts */}
        <section>
          <SectionTitle>Attention alerts</SectionTitle>
          <p className="mb-3 text-xs text-fg-muted">
            When Claude waits for your approval, answers, or a reply — blink in the sidebar, optional sound, and a desktop notification when DevScope is in the background.
          </p>
          <label className="mb-2 flex cursor-pointer items-center gap-3">
            <ToggleSwitch
              checked={attentionPrefs.enabled}
              onChange={(v) => patchAttentionPrefs({ enabled: v })}
            />
            <span className="text-xs text-fg">Enable attention alerts</span>
          </label>
          {attentionPrefs.enabled && (
            <div className="ml-1 space-y-2 border-l border-line pl-3">
              <label className="flex cursor-pointer items-center gap-3">
                <ToggleSwitch
                  checked={attentionPrefs.sound}
                  onChange={(v) => patchAttentionPrefs({ sound: v })}
                />
                <span className="text-xs text-fg-muted">Play sound</span>
              </label>
              <label className="flex cursor-pointer items-center gap-3">
                <ToggleSwitch
                  checked={attentionPrefs.flashTitle}
                  onChange={(v) => patchAttentionPrefs({ flashTitle: v })}
                />
                <span className="text-xs text-fg-muted">Flash panel title when hidden</span>
              </label>
              <label className="flex cursor-pointer items-center gap-3">
                <ToggleSwitch
                  checked={attentionPrefs.desktopNotification}
                  onChange={(v) => void handleDesktopNotificationToggle(v)}
                />
                <span className="text-xs text-fg-muted">Desktop notification</span>
              </label>
              <label className="flex cursor-pointer items-center gap-3">
                <ToggleSwitch
                  checked={attentionPrefs.alertWhenActive}
                  onChange={(v) => patchAttentionPrefs({ alertWhenActive: v })}
                />
                <span className="text-xs text-fg-muted">Sound/notify even on the open session</span>
              </label>
            </div>
          )}
        </section>

        {/* Voice input */}
        <section>
          <SectionTitle>Voice input</SectionTitle>
          <p className="mb-3 text-xs text-fg-muted">
            Chrome לא מציג בקשת מיקרופון בתוך ה-side panel. לחץ כאן פעם אחת (דף של התוסף, לא אתר חיצוני), אשר, ואז השתמש באייקון המיקרופון ליד Send — לא ב-Listen ולא ב-Record.
          </p>
          <button
            type="button"
            onClick={() => void openMicGrantPage()}
            className="mb-3 rounded-md border border-line bg-surface px-3 py-2 text-xs text-fg transition-colors hover:border-signal/40 hover:bg-signal-subtle"
          >
            Enable microphone
          </button>
          <div className="flex items-center gap-2">
            <span className="text-xs text-fg-muted">שפת דיקטיון (מיקרופון)</span>
            <select
              value={dictationLang}
              onChange={(e) => handleDictationLangChange(e.target.value as DictationLang)}
              className="rounded-md border border-line bg-surface-overlay px-2 py-1.5 text-xs text-fg outline-none transition-colors duration-fast ease-tool focus:border-signal"
            >
              <option value="he">עברית (he-IL)</option>
              <option value="en">English (en-US)</option>
            </select>
          </div>
          <p className="mt-2 text-2xs text-fg-subtle">
            כשהתיבה ריקה — המיקרופון משתמש בשפה הזו. אם כבר כתבת טקסט, השפה נקבעת לפי התוכן.
          </p>
        </section>

        {/* Context efficiency */}
        <section>
          <SectionTitle>Context &amp; efficiency</SectionTitle>
          <p className="mb-3 text-xs text-fg-muted">
            מקטין היסטוריה ארוכה ושומר תקצירים ב־<code className="font-mono">~/.dev-bridge/notes/</code>.
            Auto-compact לפי tokens מגיע מה-bridge (מומלץ). הערך למטה הוא תוסף ישן מה-extension — השאר 0.
          </p>
          <label className="mb-3 flex cursor-pointer items-center gap-3">
            <ToggleSwitch
              checked={contextPrefs.autoBindFocusedTab}
              onChange={(v) => patchContextPrefs({ autoBindFocusedTab: v })}
            />
            <span className="text-xs text-fg">Auto-bind focused tab when sending (if none bound) — off by default so the agent does not hijack your current tab</span>
          </label>
          <div className="flex items-center gap-2">
            <span className="text-xs text-fg-muted">Auto-compact every N user messages</span>
            <select
              value={contextPrefs.autoCompactEvery}
              onChange={(e) => patchContextPrefs({ autoCompactEvery: Number(e.target.value) })}
              className="rounded-md border border-line bg-surface-overlay px-2 py-1.5 text-xs text-fg outline-none transition-colors duration-fast ease-tool focus:border-signal"
            >
              <option value={0}>Off</option>
              <option value={6}>6</option>
              <option value={8}>8</option>
              <option value={12}>12</option>
              <option value={16}>16</option>
              <option value={24}>24</option>
            </select>
          </div>
          <p className="mt-2 text-2xs text-fg-subtle">
            אחרי N הודעות משתמש — תקציר אוטומטי; ההודעה הבאה מקבלת את התקציר כהקשר.
          </p>
        </section>

        {/* Browser automation */}
        <section>
          <SectionTitle>Browser automation</SectionTitle>
          <p className="mb-3 text-xs text-fg-muted">
            How DevScope drives your live Chrome tab. CDP shows a short &quot;DevScope is debugging&quot; banner.
          </p>
          <div className="mb-3 flex flex-col gap-2">
            {BROWSE_BACKENDS.map((b) => (
              <label key={b.id} className="flex cursor-pointer items-start gap-2">
                <input
                  type="radio"
                  name="browseBackend"
                  checked={browseBackend === b.id}
                  onChange={() => {
                    setBrowseBackend(b.id);
                    saveBrowseBackend(b.id).catch(() => {});
                  }}
                  className="mt-0.5"
                />
                <span className="text-xs">
                  <span className="font-medium text-fg">{b.label}</span>
                  <span className="block text-fg-muted">{b.summary}</span>
                </span>
              </label>
            ))}
          </div>
          <label className="mb-2 flex cursor-pointer items-center gap-3">
            <ToggleSwitch
              checked={uiPrefs.showClickHighlights}
              onChange={(v) => patchUiPrefs({ showClickHighlights: v })}
            />
            <span className="text-xs text-fg">Show click highlights on the page when the agent acts</span>
          </label>
          <label className="mb-2 flex cursor-pointer items-center gap-3">
            <ToggleSwitch
              checked={uiPrefs.actionSound}
              onChange={(v) => patchUiPrefs({ actionSound: v })}
            />
            <span className="text-xs text-fg">Play a short sound when browser actions complete</span>
          </label>
          <label className="flex cursor-pointer items-center gap-3">
            <ToggleSwitch
              checked={uiPrefs.streamDebug}
              onChange={(v) => patchUiPrefs({ streamDebug: v })}
            />
            <span className="text-xs text-fg">
              Stream debug panel — show live turn/WS/transcript status (also logs{' '}
              <code className="text-2xs">DevScope:stream</code> to the side-panel console)
            </span>
          </label>
        </section>

        {/* English Coach */}
        <section>
          <SectionTitle>English coach</SectionTitle>
          <p className="mb-3 text-xs text-fg-muted">
            After each message, a short lesson appears in your native language — corrections, a grammar tip, and a phrase to learn.
          </p>
          <label className="mb-3 flex cursor-pointer items-center gap-3">
            <ToggleSwitch checked={coachEnabled} onChange={handleCoachEnabledChange} />
            <span className="text-xs text-fg">Enable English coaching</span>
          </label>
          {coachEnabled && (
            <div className="ml-1 space-y-3 border-l border-line pl-3">
              <div className="flex items-center gap-2">
                <span className="text-xs text-fg-muted">Native language</span>
                <select
                  value={coachLang}
                  onChange={(e) => handleCoachLangChange(e.target.value)}
                  className="rounded-md border border-line bg-surface-overlay px-2 py-1.5 text-xs text-fg outline-none transition-colors duration-fast ease-tool focus:border-signal"
                >
                  <option value="he">עברית (Hebrew)</option>
                  <option value="ar">العربية (Arabic)</option>
                  <option value="ru">Русский (Russian)</option>
                  <option value="fr">Français (French)</option>
                  <option value="es">Español (Spanish)</option>
                  <option value="en">English</option>
                </select>
              </div>
              <div>
                <p className="mb-1.5 text-xs text-fg-muted">Focus on</p>
                <div className="space-y-1.5">
                  {COACH_FOCUS_OPTIONS.map(({ key, label }) => (
                    <label key={key} className="flex cursor-pointer items-center gap-2">
                      <CheckBox
                        checked={coachFocus.includes(key)}
                        onChange={() => handleCoachFocusToggle(key)}
                      />
                      <span className="text-xs text-fg">{label}</span>
                    </label>
                  ))}
                </div>
                <p className="mt-1.5 text-2xs text-fg-subtle">
                  If all are unchecked, all areas are covered.
                </p>
              </div>
            </div>
          )}
        </section>

        <OrchestratorSettings />

        <EmployeeSettings />

        {/* Project paths */}
        <section>
          <SectionTitle>Project paths</SectionTitle>
          <p className="mb-3 text-xs text-fg-muted">
            These appear in the "New chat" modal when choosing a project.
          </p>

          {projectPaths.length === 0 ? (
            <p className="mb-3 text-xs italic text-fg-subtle">No paths added yet.</p>
          ) : (
            <ul className="mb-3 space-y-1">
              {projectPaths.map((path) => (
                <li
                  key={path}
                  className="flex items-center gap-2 rounded-md border border-line bg-surface-overlay px-3 py-2"
                >
                  <FolderOpen size={13} strokeWidth={1.75} className="flex-shrink-0 text-fg-subtle" />
                  <span className="flex-1 truncate font-mono text-xs text-fg-muted" title={path}>
                    {path}
                  </span>
                  <button
                    onClick={() => handleDeletePath(path)}
                    aria-label={`Remove ${path}`}
                    className="flex-shrink-0 rounded p-0.5 text-fg-subtle transition-colors duration-fast ease-tool hover:bg-danger-subtle hover:text-danger"
                  >
                    <X size={12} strokeWidth={2.5} />
                  </button>
                </li>
              ))}
            </ul>
          )}

          <div className="flex gap-2">
            <button
              onClick={() => setPickerOpen(true)}
              title="Browse folders on this computer"
              className="flex items-center gap-1.5 whitespace-nowrap rounded-md border border-line px-3 py-2 text-xs font-medium text-fg-muted transition-colors duration-fast ease-tool hover:border-signal/50 hover:text-fg"
            >
              <FolderOpen size={13} strokeWidth={1.75} />
              Browse…
            </button>
            <input
              type="text"
              value={newPath}
              onChange={(e) => {
                setNewPath(e.target.value);
                setPathError('');
              }}
              onKeyDown={handlePathKeyDown}
              placeholder="/absolute/path/to/project"
              className={`min-w-0 flex-1 rounded-md border bg-surface-overlay px-3 py-2 font-mono text-xs text-fg outline-none transition-colors duration-fast ease-tool ${
                pathError ? 'border-danger focus:border-danger' : 'border-line focus:border-signal'
              }`}
            />
            <button
              onClick={handleAddPath}
              className="whitespace-nowrap rounded-md bg-signal px-3 py-2 text-xs font-medium text-signal-contrast transition-colors duration-fast ease-tool hover:bg-signal-hover"
            >
              Add
            </button>
          </div>
          {pathError && <p className="mt-1 text-xs text-danger">{pathError}</p>}
        </section>

        {pickerOpen && (
          <FolderPickerModal
            onSelect={handleFolderPicked}
            onClose={() => setPickerOpen(false)}
          />
        )}
      </div>
    </div>
  );
}

const COACH_FOCUS_OPTIONS: { key: CoachFocus; label: string }[] = [
  { key: 'vocabulary', label: 'אוצר מילים (vocabulary & word choice)' },
  { key: 'grammar', label: 'דקדוק (grammar & tense)' },
  { key: 'spelling', label: 'כתיב (spelling & typos)' },
  { key: 'sentences', label: 'הרכבת משפטים (sentence structure)' },
];

function CheckBox({ checked, onChange }: { checked: boolean; onChange: () => void }) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={checked}
      onClick={onChange}
      className={`flex h-4 w-4 flex-shrink-0 items-center justify-center rounded border transition-colors duration-fast ease-tool focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-signal ${
        checked ? 'border-signal bg-signal text-signal-contrast' : 'border-line bg-surface-overlay'
      }`}
    >
      {checked && (
        <svg width="9" height="7" viewBox="0 0 9 7" fill="none" aria-hidden>
          <path d="M1 3.5L3.5 6L8 1" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      )}
    </button>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="mb-2 text-2xs font-semibold uppercase tracking-wider text-fg-subtle">{children}</h3>
  );
}

const THEME_OPTIONS: { value: ThemePref; label: string }[] = [
  { value: 'system', label: 'System' },
  { value: 'light', label: 'Light' },
  { value: 'dark', label: 'Dark' },
  { value: 'dim', label: 'Dim' },
];

function ThemeToggle({ pref, onChange }: { pref: ThemePref; onChange: (p: ThemePref) => void }) {
  return (
    <div className="inline-flex rounded-md border border-line p-0.5 text-xs">
      {THEME_OPTIONS.map((opt) => (
        <button
          key={opt.value}
          type="button"
          onClick={() => onChange(opt.value)}
          className={`rounded-[4px] px-3 py-1 font-medium transition-colors duration-fast ease-tool ${
            pref === opt.value ? 'bg-fg text-surface' : 'text-fg-muted hover:text-fg'
          }`}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

const INTERACTION_MODE_OPTIONS: { value: InteractionMode; label: string }[] = [
  { value: 'terminal', label: 'Terminal (recommended)' },
  { value: 'stream', label: 'Stream chat (legacy)' },
];

function InteractionModeToggle({
  mode,
  onChange,
}: {
  mode: InteractionMode;
  onChange: (m: InteractionMode) => void;
}) {
  return (
    <div className="inline-flex rounded-md border border-line p-0.5 text-xs">
      {INTERACTION_MODE_OPTIONS.map((opt) => (
        <button
          key={opt.value}
          type="button"
          onClick={() => onChange(opt.value)}
          className={`rounded-[4px] px-3 py-1 font-medium transition-colors duration-fast ease-tool ${
            mode === opt.value ? 'bg-fg text-surface' : 'text-fg-muted hover:text-fg'
          }`}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

const PRODUCT_MODE_OPTIONS: { value: ProductMode; label: string }[] = [
  { value: 'pro', label: 'Pro' },
  { value: 'consumer', label: 'Simple' },
];

function ProductModeToggle({
  mode,
  onChange,
}: {
  mode: ProductMode;
  onChange: (m: ProductMode) => void;
}) {
  return (
    <div className="inline-flex rounded-md border border-line p-0.5 text-xs">
      {PRODUCT_MODE_OPTIONS.map((opt) => (
        <button
          key={opt.value}
          type="button"
          onClick={() => onChange(opt.value)}
          className={`rounded-[4px] px-3 py-1 font-medium transition-colors duration-fast ease-tool ${
            mode === opt.value ? 'bg-fg text-surface' : 'text-fg-muted hover:text-fg'
          }`}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

function ToggleSwitch({
  checked,
  onChange,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-5 w-9 flex-shrink-0 items-center rounded-full border transition-colors duration-fast ease-tool focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-signal ${
        checked ? 'border-signal bg-signal' : 'border-line bg-surface-overlay'
      }`}
    >
      <span
        className={`inline-block h-3.5 w-3.5 rounded-full transition-transform duration-fast ease-tool ${
          checked
            ? 'translate-x-[18px] bg-surface'
            : 'translate-x-[2px] bg-fg-subtle'
        }`}
      />
    </button>
  );
}

function TestResult({ state }: { state: TestState }) {
  if (state === 'idle') return null;
  if (state === 'testing') {
    return (
      <span className="flex items-center gap-1 text-xs text-fg-muted">
        <Loader2 size={13} strokeWidth={2} className="animate-spin" />
        Testing…
      </span>
    );
  }
  if (state === 'connected') {
    return (
      <span className="flex items-center gap-1 text-xs text-success">
        <Check size={13} strokeWidth={2.5} />
        Connected
      </span>
    );
  }
  return (
    <span className="flex items-center gap-1 text-xs text-danger">
      <AlertCircle size={13} strokeWidth={2} />
      {state === 'unauthorized' ? 'Bad token' : 'Bridge offline'}
    </span>
  );
}
