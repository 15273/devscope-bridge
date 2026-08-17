/**
 * CapabilitiesPanel — DevScope MCP servers + Claude skills readiness.
 */
import { useCallback, useEffect, useState } from 'react';
import { Check, Loader2, RefreshCw, X } from 'lucide-react';
import { fetchCapabilities, type DevScopeCapabilities } from '../bridge';

export function CapabilitiesPanel() {
  const [data, setData] = useState<DevScopeCapabilities | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    const caps = await fetchCapabilities();
    if (!caps) {
      setError('Could not load capabilities — check bridge connection');
      setData(null);
    } else {
      setData(caps);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return (
    <section>
      <div className="mb-2 flex items-center justify-between gap-2">
        <h3 className="text-2xs font-semibold uppercase tracking-wider text-fg-subtle">
          Agent capabilities
        </h3>
        <button
          type="button"
          onClick={() => void refresh()}
          disabled={loading}
          className="flex items-center gap-1 rounded-sm px-1.5 py-0.5 text-2xs text-fg-muted transition-colors hover:bg-surface-overlay hover:text-fg"
        >
          {loading ? <Loader2 size={11} className="animate-spin" /> : <RefreshCw size={11} />}
          Refresh
        </button>
      </div>
      <p className="mb-3 text-xs text-fg-muted">
        Claude sessions in DevScope use these MCP tools (from <code className="font-mono">.mcp.json</code>)
        and skills in <code className="font-mono">.claude/skills/</code>.
      </p>

      {error && (
        <p className="mb-2 text-xs text-warning">{error}</p>
      )}

      {data && (
        <>
          <ul className="space-y-2">
            {data.mcp_servers.map((srv) => (
              <li
                key={srv.id}
                className="rounded-md border border-line bg-surface-raised px-3 py-2"
              >
                <div className="flex items-start gap-2">
                  {srv.ready ? (
                    <Check size={14} className="mt-0.5 flex-shrink-0 text-signal" />
                  ) : (
                    <X size={14} className="mt-0.5 flex-shrink-0 text-warning" />
                  )}
                  <div className="min-w-0 flex-1">
                    <p className="text-xs font-medium text-fg">
                      {srv.label}
                      <span className="ml-1.5 font-mono text-2xs font-normal text-fg-subtle">
                        {srv.id}
                      </span>
                    </p>
                    <p className="mt-0.5 text-2xs text-fg-muted">{srv.description}</p>
                    <p className="mt-1 font-mono text-[10px] text-fg-subtle">{srv.tools_hint}</p>
                    {!srv.ready && srv.status?.hint && (
                      <p className="mt-1 text-2xs text-warning">{String(srv.status.hint)}</p>
                    )}
                    {!srv.ready && srv.status?.setup_command && (
                      <p className="mt-1 break-all font-mono text-[10px] text-fg-subtle">
                        {String(srv.status.setup_command)}
                      </p>
                    )}
                  </div>
                </div>
              </li>
            ))}
          </ul>

          <div className="mt-3 rounded-md border border-line bg-surface-overlay px-3 py-2">
            <p className="text-2xs font-medium text-fg-muted">Claude skills (auto-loaded from repo)</p>
            <ul className="mt-1 space-y-0.5">
              {data.skills.map((s) => (
                <li key={s.id} className="font-mono text-[10px] text-fg-subtle">
                  {s.label} — {s.path}
                </li>
              ))}
            </ul>
            <p className="mt-2 text-[10px] text-fg-subtle">
              One-time MCP registration:{' '}
              <code className="font-mono">{data.setup.claude_setup}</code>
            </p>
          </div>
        </>
      )}
    </section>
  );
}
