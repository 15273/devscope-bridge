/**
 * EmployeeSettings — Settings section for the Autonomous Employee:
 * master switch, external board (Notion) sync, communication channels,
 * and the daily digest. All opt-in; defaults keep today's behavior.
 */
import { useCallback, useEffect, useState } from 'react';
import { Check, Loader2 } from 'lucide-react';
import {
  fetchEmployeeConfig,
  patchEmployeeConfig,
  testEmployeeChannel,
  type EmployeeConfig,
} from '../bridge';

const CHANNEL_LABELS: Record<string, string> = {
  panel: 'DevScope panel',
  notion: 'Notion comments',
  whatsapp: 'WhatsApp',
  email: 'Email digest',
};

export function EmployeeSettings() {
  const [cfg, setCfg] = useState<EmployeeConfig | null>(null);
  const [testing, setTesting] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<string>('');

  useEffect(() => {
    fetchEmployeeConfig().then(setCfg).catch(() => {});
  }, []);

  const patch = useCallback((fields: Partial<EmployeeConfig>) => {
    setCfg((prev) => (prev ? { ...prev, ...fields } : prev));
    void patchEmployeeConfig(fields).then((saved) => {
      if (saved) setCfg(saved);
    });
  }, []);

  const runTest = useCallback(async (channel: string) => {
    setTesting(channel);
    setTestResult('');
    const ok = await testEmployeeChannel(channel);
    setTesting(null);
    setTestResult(ok ? `${channel}: sent ✓` : `${channel}: failed`);
  }, []);

  if (cfg === null) return null;

  return (
    <section>
      <h2 className="mb-2 text-sm font-semibold text-fg">Autonomous employee</h2>
      <p className="mb-3 text-xs text-fg-muted">
        An always-on agent that manages the task board end-to-end: pulls tasks from
        Notion, breaks big projects into steps, asks when stuck, and reports progress.
      </p>

      <label className="mb-3 flex cursor-pointer items-center gap-3">
        <EmpToggle
          checked={cfg.employee_enabled}
          onChange={(v) => patch({ employee_enabled: v })}
        />
        <span className="text-xs text-fg">Enable autonomous employee</span>
      </label>

      {cfg.employee_enabled && (
        <div className="ml-1 space-y-4 border-l border-line pl-3">
          <div>
            <p className="mb-1.5 text-xs font-medium text-fg">Notion board</p>
            <input
              value={cfg.board_database}
              onChange={(e) => patch({ board_database: e.target.value })}
              placeholder="Notion database name or URL"
              className="w-full rounded-md border border-line bg-surface px-2 py-1.5 text-xs text-fg placeholder:text-fg-subtle"
            />
            <label className="mt-2 flex cursor-pointer items-center gap-3">
              <EmpToggle
                checked={cfg.board_sync_enabled}
                onChange={(v) => patch({ board_sync_enabled: v })}
              />
              <span className="text-xs text-fg-muted">
                Two-way sync (pull tasks, push status + comments)
              </span>
            </label>
          </div>

          <div>
            <p className="mb-1.5 text-xs font-medium text-fg">Update channels</p>
            <div className="space-y-1.5">
              {Object.keys(CHANNEL_LABELS).map((channel) => (
                <div key={channel} className="flex items-center gap-3">
                  <EmpToggle
                    checked={!!cfg.channels[channel]}
                    onChange={(v) => patch({ channels: { ...cfg.channels, [channel]: v } })}
                  />
                  <span className="flex-1 text-xs text-fg-muted">
                    {CHANNEL_LABELS[channel]}
                  </span>
                  <button
                    type="button"
                    disabled={testing !== null}
                    onClick={() => void runTest(channel)}
                    className="rounded-sm px-1.5 py-0.5 text-2xs text-signal hover:bg-signal-subtle disabled:opacity-50"
                  >
                    {testing === channel ? (
                      <Loader2 size={11} className="animate-spin" />
                    ) : (
                      'Test'
                    )}
                  </button>
                </div>
              ))}
            </div>
            {testResult && (
              <p className="mt-1.5 flex items-center gap-1 text-2xs text-fg-muted">
                <Check size={11} className="text-signal" /> {testResult}
              </p>
            )}
          </div>

          {cfg.channels.whatsapp && (
            <div>
              <p className="mb-1.5 text-xs font-medium text-fg">WhatsApp chat ID</p>
              <input
                value={cfg.wa_chat_id}
                onChange={(e) => patch({ wa_chat_id: e.target.value })}
                placeholder="e.g. 9725...@c.us"
                className="w-full rounded-md border border-line bg-surface px-2 py-1.5 text-xs text-fg placeholder:text-fg-subtle"
              />
            </div>
          )}

          <div>
            <p className="mb-1.5 text-xs font-medium text-fg">Daily digest</p>
            <div className="flex items-center gap-2">
              <input
                value={cfg.digest_daily_at}
                onChange={(e) => patch({ digest_daily_at: e.target.value })}
                placeholder="18:00"
                className="w-20 rounded-md border border-line bg-surface px-2 py-1.5 text-xs text-fg"
              />
              {cfg.channels.email && (
                <input
                  value={cfg.digest_email}
                  onChange={(e) => patch({ digest_email: e.target.value })}
                  placeholder="Email (empty = to yourself)"
                  className="min-w-0 flex-1 rounded-md border border-line bg-surface px-2 py-1.5 text-xs text-fg placeholder:text-fg-subtle"
                />
              )}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

function EmpToggle({
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
          checked ? 'translate-x-[18px] bg-surface' : 'translate-x-[2px] bg-fg-subtle'
        }`}
      />
    </button>
  );
}
