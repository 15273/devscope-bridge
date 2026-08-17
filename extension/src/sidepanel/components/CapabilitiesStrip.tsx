/**
 * CapabilitiesStrip — compact chips above the composer (consumer product mode)
 * showing what DevScope can do right now: Browser ✓ · Notion ✗ Connect · Gmail ✓.
 * Fed by the bridge capability registry (GET /capabilities → `capabilities`).
 */
import { useEffect, useState } from 'react';
import { Check, X } from 'lucide-react';
import { fetchCapabilities, type RegistryCapability } from '../bridge';

const REFRESH_MS = 60_000;

interface CapabilitiesStripProps {
  onOpenSettings: () => void;
}

export function CapabilitiesStrip({ onOpenSettings }: CapabilitiesStripProps) {
  const [caps, setCaps] = useState<RegistryCapability[]>([]);

  useEffect(() => {
    let cancelled = false;
    const load = () => {
      fetchCapabilities()
        .then((result) => {
          if (!cancelled && result?.capabilities) {
            setCaps(result.capabilities.filter((c) => c.consumer_visible));
          }
        })
        .catch(() => {});
    };
    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  if (caps.length === 0) return null;

  return (
    <div className="flex flex-wrap items-center gap-1.5 border-b border-line bg-surface-raised px-3 py-1.5">
      {caps.map((cap) => (
        <span
          key={cap.id}
          title={cap.available ? cap.description : cap.setup_hint ?? cap.description}
          className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] ${
            cap.available
              ? 'border-line text-fg-muted'
              : 'border-line text-fg-subtle'
          }`}
        >
          {cap.available ? (
            <Check size={11} className="text-signal" aria-label="available" />
          ) : (
            <X size={11} aria-label="unavailable" />
          )}
          {cap.label}
          {!cap.available && (
            <button
              type="button"
              onClick={onOpenSettings}
              className="ml-0.5 font-medium text-signal hover:underline"
            >
              Connect
            </button>
          )}
        </span>
      ))}
    </div>
  );
}
