/**
 * CockpitSettings — scope/threshold configuration panel.
 *
 * Allows editing: threshold hours, DM-in-scope toggle,
 * group allowlist (add/remove chat IDs), blacklist (add/remove chat IDs).
 * "שמור" calls saveSettings with the current patch.
 */
import { useState, useCallback } from 'react';
import { X, Plus } from 'lucide-react';
import type { CockpitSettings as SettingsType, UseCockpitReturn } from './useCockpit';

interface CockpitSettingsProps {
  settings: SettingsType;
  onSave: UseCockpitReturn['saveSettings'];
  onClose: () => void;
}

// ── Small sub-components ──────────────────────────────────────────────────────

interface TagListProps {
  label: string;
  items: string[];
  onAdd: (value: string) => void;
  onRemove: (value: string) => void;
  placeholder: string;
}

function TagList({ label, items, onAdd, onRemove, placeholder }: TagListProps) {
  const [inputVal, setInputVal] = useState('');

  const handleAdd = useCallback(() => {
    const v = inputVal.trim();
    if (!v || items.includes(v)) return;
    onAdd(v);
    setInputVal('');
  }, [inputVal, items, onAdd]);

  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-2xs font-medium text-fg-muted">{label}</span>
      <div className="flex flex-wrap gap-1">
        {items.map((item) => (
          <span
            key={item}
            className="flex items-center gap-1 rounded-sm border border-line bg-surface px-1.5 py-0.5 text-2xs text-fg"
          >
            {item}
            <button
              type="button"
              onClick={() => onRemove(item)}
              className="text-fg-subtle hover:text-danger"
              aria-label={`הסר ${item}`}
            >
              <X size={10} />
            </button>
          </span>
        ))}
      </div>
      <div className="flex gap-1">
        <input
          dir="ltr"
          type="text"
          value={inputVal}
          onChange={(e) => setInputVal(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleAdd()}
          placeholder={placeholder}
          className="h-7 min-w-0 flex-1 rounded-md border border-line bg-surface px-2 text-xs text-fg placeholder:text-fg-subtle focus:border-signal focus:outline-none"
        />
        <button
          type="button"
          onClick={handleAdd}
          className="flex h-7 w-7 items-center justify-center rounded-md border border-line bg-surface text-fg-muted transition-colors duration-fast ease-tool hover:bg-surface-overlay hover:text-fg"
          aria-label="הוסף"
        >
          <Plus size={13} />
        </button>
      </div>
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────────────────────

export function CockpitSettings({ settings, onSave, onClose }: CockpitSettingsProps) {
  const [threshold, setThreshold] = useState(settings.threshold_hours);
  const [dmInScope, setDmInScope] = useState(settings.dm_in_scope);
  const [allowlist, setAllowlist] = useState<string[]>(settings.group_allowlist);
  const [blacklist, setBlacklist] = useState<string[]>(settings.blacklist);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const handleSave = useCallback(async () => {
    setSaving(true);
    setSaveError(null);
    try {
      await onSave({
        threshold_hours: threshold,
        dm_in_scope: dmInScope,
        group_allowlist: allowlist,
        blacklist,
      });
      onClose();
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : String(e));
      setSaving(false);
    }
  }, [threshold, dmInScope, allowlist, blacklist, onSave, onClose]);

  return (
    <div
      dir="rtl"
      className="flex flex-col gap-4 rounded-md border border-line bg-surface p-4"
    >
      {/* Header */}
      <div className="flex items-center justify-between">
        <span className="text-sm font-semibold text-fg">הגדרות קוקפיט</span>
        <button
          type="button"
          onClick={onClose}
          className="flex h-6 w-6 items-center justify-center rounded text-fg-subtle transition-colors duration-fast ease-tool hover:bg-surface-overlay hover:text-fg"
          aria-label="סגור"
        >
          <X size={14} />
        </button>
      </div>

      {/* Threshold */}
      <div className="flex flex-col gap-1.5">
        <label className="text-2xs font-medium text-fg-muted">
          זמן המתנה לפני נאג (שעות)
        </label>
        <input
          type="number"
          min={1}
          max={72}
          value={threshold}
          onChange={(e) => setThreshold(Number(e.target.value))}
          className="h-8 w-24 rounded-md border border-line bg-surface px-2 text-xs text-fg focus:border-signal focus:outline-none"
        />
      </div>

      {/* DM toggle */}
      <div className="flex items-center justify-between">
        <span className="text-xs text-fg">כלול שיחות פרטיות</span>
        <button
          type="button"
          role="switch"
          aria-checked={dmInScope}
          onClick={() => setDmInScope((v) => !v)}
          className={[
            'relative h-5 w-9 rounded-full transition-colors duration-fast ease-tool focus:outline-none',
            dmInScope ? 'bg-signal' : 'bg-line-strong',
          ].join(' ')}
        >
          <span
            className={[
              'absolute top-0.5 h-4 w-4 rounded-full bg-white shadow-tool transition-transform duration-fast ease-tool',
              dmInScope ? 'translate-x-4' : 'translate-x-0.5',
            ].join(' ')}
          />
        </button>
      </div>

      {/* Group allowlist */}
      <TagList
        label="קבוצות בתחולה (מזהי שיחה)"
        items={allowlist}
        onAdd={(v) => setAllowlist((prev) => [...prev, v])}
        onRemove={(v) => setAllowlist((prev) => prev.filter((i) => i !== v))}
        placeholder="120363…@g.us"
      />

      {/* Blacklist */}
      <TagList
        label="רשימה שחורה (מזהי שיחה)"
        items={blacklist}
        onAdd={(v) => setBlacklist((prev) => [...prev, v])}
        onRemove={(v) => setBlacklist((prev) => prev.filter((i) => i !== v))}
        placeholder="972501234567@c.us"
      />

      {/* Save error */}
      {saveError && (
        <p className="rounded-sm bg-danger-subtle px-2 py-1 text-2xs text-danger">{saveError}</p>
      )}

      {/* Save button */}
      <button
        type="button"
        disabled={saving}
        onClick={handleSave}
        className="flex h-8 w-full items-center justify-center rounded-md bg-signal text-xs font-semibold text-signal-contrast transition-colors duration-fast ease-tool hover:bg-signal-hover disabled:cursor-wait disabled:opacity-60"
      >
        {saving ? 'שומר…' : 'שמור'}
      </button>
    </div>
  );
}
