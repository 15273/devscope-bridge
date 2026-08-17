/**
 * PluginStore — install MCP plugins from inside DevScope, like an app store.
 *
 * Catalog = curated featured list + live search of the official MCP Registry
 * (always up to date). Install registers the remote server for cursor-agent;
 * OAuth plugins get a Login button (browser flow). Once ready, a plugin is
 * automatically available to Claude (devscope_invoke) and the autonomous
 * employee — no further wiring.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { Check, Download, KeyRound, Loader2, RefreshCw, Search } from 'lucide-react';
import {
  fetchStoreCatalog,
  fetchStoreState,
  installStorePlugin,
  loginStorePlugin,
  type InstalledPlugin,
  type StoreCatalogItem,
} from '../bridge';

export function PluginStore() {
  const [query, setQuery] = useState('');
  const [items, setItems] = useState<StoreCatalogItem[]>([]);
  const [installed, setInstalled] = useState<Map<string, InstalledPlugin>>(new Map());
  const [searching, setSearching] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [notice, setNotice] = useState('');
  const debounceRef = useRef<ReturnType<typeof setTimeout>>();

  const refreshState = useCallback(async () => {
    const plugins = await fetchStoreState();
    setInstalled(new Map(plugins.map((p) => [p.id, p])));
  }, []);

  useEffect(() => {
    void fetchStoreCatalog('').then(setItems);
    void refreshState();
  }, [refreshState]);

  useEffect(() => {
    clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      setSearching(true);
      void fetchStoreCatalog(query)
        .then(setItems)
        .finally(() => setSearching(false));
    }, 350);
    return () => clearTimeout(debounceRef.current);
  }, [query]);

  const handleInstall = useCallback(
    async (item: StoreCatalogItem) => {
      setBusyId(item.id);
      setNotice('');
      const result = await installStorePlugin(item);
      setBusyId(null);
      if (!result.ok) {
        setNotice(result.error ?? 'Install failed');
      } else if (result.needs_login) {
        setNotice(`${item.title} installed — sign in to connect it.`);
      } else {
        setNotice(`${item.title} installed and ready. Available to chat within a minute.`);
      }
      await refreshState();
    },
    [refreshState],
  );

  const handleLogin = useCallback(
    async (id: string) => {
      setBusyId(id);
      setNotice('');
      const ok = await loginStorePlugin(id);
      setBusyId(null);
      setNotice(ok
        ? 'Approve the request in the browser tab that opened, then hit refresh.'
        : 'Could not start the sign-in flow.');
    },
    [],
  );

  return (
    <section>
      <div className="mb-2 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-fg">Plugin store</h2>
        <button
          type="button"
          onClick={() => void refreshState()}
          aria-label="Refresh plugin status"
          className="rounded-md p-1 text-fg-subtle hover:bg-surface-raised hover:text-fg"
        >
          <RefreshCw size={13} />
        </button>
      </div>
      <p className="mb-3 text-xs text-fg-muted">
        Connect services (Notion, Linear, GitHub…) in one click. Installed plugins become
        available to the chat and the autonomous employee automatically.
      </p>

      <div className="relative mb-3">
        <Search size={13} className="absolute right-2.5 top-2 text-fg-subtle" />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search the MCP registry…"
          className="w-full rounded-md border border-line bg-surface py-1.5 pl-3 pr-8 text-xs text-fg placeholder:text-fg-subtle"
        />
      </div>

      {notice && <p className="mb-2 text-2xs text-signal">{notice}</p>}

      <ul className="max-h-72 space-y-1.5 overflow-y-auto">
        {searching && items.length === 0 && (
          <li className="py-2 text-center text-2xs text-fg-subtle">Searching…</li>
        )}
        {!searching && items.length === 0 && (
          <li className="py-2 text-center text-2xs text-fg-subtle">No plugins found.</li>
        )}
        {items.map((item) => (
          <PluginRow
            key={`${item.source}-${item.id}`}
            item={item}
            state={installed.get(item.id)}
            busy={busyId === item.id}
            onInstall={() => void handleInstall(item)}
            onLogin={() => void handleLogin(item.id)}
          />
        ))}
      </ul>
    </section>
  );
}

function PluginRow({
  item,
  state,
  busy,
  onInstall,
  onLogin,
}: {
  item: StoreCatalogItem;
  state: InstalledPlugin | undefined;
  busy: boolean;
  onInstall: () => void;
  onLogin: () => void;
}) {
  return (
    <li className="flex items-start gap-2.5 rounded-md border border-line/70 bg-surface-raised px-2.5 py-2">
      <div className="min-w-0 flex-1">
        <p className="flex items-center gap-1.5 text-xs font-medium text-fg">
          {item.title}
          {item.source === 'featured' && (
            <span className="rounded bg-signal-subtle px-1 py-px text-2xs text-signal">
              Featured
            </span>
          )}
        </p>
        <p className="mt-0.5 line-clamp-2 text-2xs text-fg-muted">{item.description}</p>
      </div>
      <PluginAction state={state} busy={busy} onInstall={onInstall} onLogin={onLogin} />
    </li>
  );
}

function PluginAction({
  state,
  busy,
  onInstall,
  onLogin,
}: {
  state: InstalledPlugin | undefined;
  busy: boolean;
  onInstall: () => void;
  onLogin: () => void;
}) {
  if (busy) {
    return <Loader2 size={14} className="mt-1 shrink-0 animate-spin text-fg-subtle" />;
  }
  if (state?.ready) {
    return (
      <span className="mt-0.5 flex shrink-0 items-center gap-1 text-2xs text-signal">
        <Check size={12} /> Ready
      </span>
    );
  }
  if (state?.needs_login) {
    return (
      <button
        type="button"
        onClick={onLogin}
        className="flex shrink-0 items-center gap-1 rounded-md border border-signal/50 px-2 py-1 text-2xs font-medium text-signal hover:bg-signal-subtle"
      >
        <KeyRound size={11} /> Sign in
      </button>
    );
  }
  if (state) {
    return (
      <span className="mt-0.5 shrink-0 text-2xs text-fg-subtle" title={state.status}>
        {state.status.slice(0, 18)}
      </span>
    );
  }
  return (
    <button
      type="button"
      onClick={onInstall}
      className="flex shrink-0 items-center gap-1 rounded-md bg-signal px-2 py-1 text-2xs font-medium text-signal-contrast hover:opacity-90"
    >
      <Download size={11} /> Install
    </button>
  );
}
