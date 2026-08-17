/**
 * FolderPickerModal — in-panel folder browser backed by the bridge
 * (GET /fs/list-dirs). Navigate into folders, then "Select this folder".
 */
import { useCallback, useEffect, useState } from 'react';
import { ArrowUp, Folder, Loader2, X } from 'lucide-react';
import { listDirs } from '../bridge';

interface FolderPickerModalProps {
  onSelect: (path: string) => void;
  onClose: () => void;
}

export function FolderPickerModal({ onSelect, onClose }: FolderPickerModalProps) {
  const [path, setPath] = useState('');
  const [parent, setParent] = useState<string | null>(null);
  const [dirs, setDirs] = useState<{ name: string; path: string }[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const navigate = useCallback(async (target: string) => {
    setLoading(true);
    setError('');
    const listing = await listDirs(target);
    setLoading(false);
    if (!listing.ok || !listing.path) {
      setError(listing.error ?? 'Failed to list folder');
      return;
    }
    setPath(listing.path);
    setParent(listing.parent ?? null);
    setDirs(listing.dirs ?? []);
  }, []);

  useEffect(() => {
    void navigate('');
  }, [navigate]);

  useEffect(() => {
    function onKey(e: globalThis.KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ backdropFilter: 'blur(4px)', backgroundColor: 'rgba(0,0,0,0.4)' }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="flex max-h-[70vh] w-[340px] flex-col rounded-lg border border-line bg-surface-overlay p-4 shadow-modal dark:shadow-modal-dark">
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-fg">Choose a project folder</h2>
          <button
            onClick={onClose}
            aria-label="Close"
            className="rounded-md p-1 text-fg-subtle hover:bg-surface-raised hover:text-fg"
          >
            <X size={14} strokeWidth={2.5} />
          </button>
        </div>

        <div className="mb-2 flex items-center gap-1.5">
          <button
            type="button"
            disabled={!parent || loading}
            onClick={() => parent && void navigate(parent)}
            aria-label="Up one folder"
            className="shrink-0 rounded-md border border-line p-1.5 text-fg-muted hover:text-fg disabled:opacity-40"
          >
            <ArrowUp size={13} />
          </button>
          <span
            dir="ltr"
            className="min-w-0 flex-1 truncate rounded-md bg-surface-raised px-2 py-1.5 font-mono text-2xs text-fg-muted"
            title={path}
          >
            {path || '…'}
          </span>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto rounded-md border border-line bg-surface">
          {loading ? (
            <p className="flex items-center justify-center gap-2 py-6 text-2xs text-fg-subtle">
              <Loader2 size={13} className="animate-spin" /> Loading…
            </p>
          ) : dirs.length === 0 ? (
            <p className="py-6 text-center text-2xs text-fg-subtle">No subfolders.</p>
          ) : (
            <ul>
              {dirs.map((d) => (
                <li key={d.path}>
                  <button
                    type="button"
                    onClick={() => void navigate(d.path)}
                    className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-xs text-fg hover:bg-surface-raised"
                  >
                    <Folder size={13} className="shrink-0 text-fg-subtle" />
                    <span dir="ltr" className="truncate">{d.name}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        {error && <p className="mt-2 text-2xs text-danger">{error}</p>}

        <div className="mt-3 flex justify-end gap-2">
          <button
            onClick={onClose}
            className="rounded-md px-3 py-1.5 text-xs text-fg-muted hover:bg-surface-raised"
          >
            Cancel
          </button>
          <button
            disabled={!path || loading}
            onClick={() => path && onSelect(path)}
            className="rounded-md bg-signal px-3 py-1.5 text-xs font-medium text-signal-contrast hover:bg-signal-hover disabled:opacity-40"
          >
            Select this folder
          </button>
        </div>
      </div>
    </div>
  );
}
