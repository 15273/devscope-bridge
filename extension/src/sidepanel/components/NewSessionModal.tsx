/**
 * NewSessionModal — creates a new dev session.
 * Fields: name, agent (segmented control), project (dropdown from saved paths).
 */
import { useState, useEffect, useCallback, useRef, KeyboardEvent } from 'react';
import { X } from 'lucide-react';
import type { Agent, CreateSessionPayload } from '@/shared/frames';
import { loadProjectPaths } from '../utils/storage';

const SESSION_NAME_RE = /^[a-zA-Z0-9_-]{1,64}$/;
const MAX_NAME = 64;

interface NewSessionModalProps {
  existingNames: string[];
  onSubmit: (payload: CreateSessionPayload) => Promise<void>;
  onClose: () => void;
}

export function NewSessionModal({ existingNames, onSubmit, onClose }: NewSessionModalProps) {
  const [name, setName] = useState('');
  const [agent, setAgent] = useState<Agent>('claude');
  const [projectPaths, setProjectPaths] = useState<string[]>([]);
  const [selectedPath, setSelectedPath] = useState('');
  const [nameError, setNameError] = useState('');
  const [submitError, setSubmitError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [claudeAgent, setClaudeAgent] = useState<string | null>(null);
  const nameRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    loadProjectPaths()
      .then((paths) => {
        setProjectPaths(paths);
        if (paths.length > 0) setSelectedPath(paths[0]);
      })
      .catch(() => {});
    nameRef.current?.focus();
  }, []);

  useEffect(() => {
    function onKey(e: globalThis.KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const validateName = useCallback(
    (val: string) => {
      if (!SESSION_NAME_RE.test(val)) return 'Only letters, numbers, _ and - (1–64 chars)';
      if (existingNames.includes(val)) return 'A session with this name already exists';
      return '';
    },
    [existingNames],
  );

  const handleNameChange = useCallback(
    (val: string) => {
      setName(val);
      setNameError(val ? validateName(val) : '');
    },
    [validateName],
  );

  const handleSubmit = useCallback(async () => {
    const err = validateName(name);
    if (err) {
      setNameError(err);
      return;
    }
    if (!selectedPath && projectPaths.length > 0) return;

    setIsSubmitting(true);
    setSubmitError('');
    try {
      await onSubmit({
        name,
        agent,
        cwd: selectedPath || '',
        ...(claudeAgent ? { claude_agent: claudeAgent, mode: 'act' as const } : {}),
      });
      onClose();
    } catch (e: unknown) {
      setSubmitError(e instanceof Error ? e.message : 'Failed to create session');
    } finally {
      setIsSubmitting(false);
    }
  }, [name, agent, claudeAgent, selectedPath, projectPaths, validateName, onSubmit, onClose]);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLInputElement>) => {
      if (e.key === 'Enter') handleSubmit();
    },
    [handleSubmit],
  );

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ backdropFilter: 'blur(4px)', backgroundColor: 'rgba(0,0,0,0.4)' }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="w-[320px] rounded-lg border border-line bg-surface-overlay p-5 shadow-modal dark:shadow-modal-dark">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-fg">New chat</h2>
          <button
            onClick={onClose}
            aria-label="Close"
            className="rounded-md p-1 text-fg-subtle transition-colors duration-fast ease-tool hover:bg-surface-raised hover:text-fg"
          >
            <X size={14} strokeWidth={2.5} />
          </button>
        </div>

        {/* Name */}
        <div className="mb-3">
          <label className="mb-1 block text-xs font-medium text-fg-muted">Name</label>
          <input
            ref={nameRef}
            type="text"
            value={name}
            maxLength={MAX_NAME}
            onChange={(e) => handleNameChange(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="e.g. feature-auth"
            className={`w-full rounded-md border bg-surface px-3 py-2 text-sm text-fg outline-none transition-colors duration-fast ease-tool ${
              nameError ? 'border-danger focus:border-danger' : 'border-line focus:border-signal'
            }`}
          />
          <div className="mt-1 flex items-center justify-between">
            <span className="text-xs text-danger">{nameError}</span>
            {name.length > 0 && (
              <span className="font-mono text-2xs text-fg-subtle">
                {name.length}/{MAX_NAME}
              </span>
            )}
          </div>
        </div>

        {/* Agent */}
        <div className="mb-3">
          <label className="mb-1 block text-xs font-medium text-fg-muted">Agent</label>
          <AgentSegment value={agent} onChange={setAgent} />
          {agent === 'cursor' && (
            <div className="mt-1.5 space-y-1 text-xs leading-snug text-fg-muted">
              <p>
                <span className="text-warning">Note:</span> Cursor delivers results in a single block (not streamed).
              </p>
              <p>
                Loads MCP from <span className="font-mono">.cursor/mcp.json</span> — browser, tasks, Notion (if enabled in Cursor), agent-hub.
              </p>
            </div>
          )}
          {agent === 'claude' && (
            <p className="mt-1.5 text-xs leading-snug text-fg-muted">
              Use <span className="font-mono">/cursor-task</span> in chat for Notion &amp; other Cursor MCP plugins without switching agent.
            </p>
          )}
        </div>

        {/* Project */}
        <div className="mb-4">
          <label className="mb-1 block text-xs font-medium text-fg-muted">Project</label>
          {projectPaths.length === 0 ? (
            <p className="text-xs text-fg-muted">
              No projects configured. <span className="text-signal">Add one in Settings →</span>
            </p>
          ) : (
            <select
              value={selectedPath}
              onChange={(e) => setSelectedPath(e.target.value)}
              className="w-full rounded-md border border-line bg-surface px-3 py-2 font-mono text-xs text-fg outline-none transition-colors duration-fast ease-tool focus:border-signal"
            >
              {projectPaths.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          )}
        </div>

        {submitError && (
          <p className="mb-3 rounded-md bg-danger-subtle px-3 py-2 text-xs text-danger">{submitError}</p>
        )}

        <div className="flex justify-end gap-2">
          <button
            onClick={onClose}
            className="rounded-md px-4 py-2 text-sm text-fg-muted transition-colors duration-fast ease-tool hover:bg-surface-raised"
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={!name || !!nameError || isSubmitting}
            className="rounded-md bg-signal px-4 py-2 text-sm font-medium text-signal-contrast transition-colors duration-fast ease-tool hover:bg-signal-hover disabled:opacity-40"
          >
            {isSubmitting ? 'Creating…' : 'Create'}
          </button>
        </div>
      </div>
    </div>
  );
}

function AgentSegment({ value, onChange }: { value: Agent; onChange: (a: Agent) => void }) {
  return (
    <div className="inline-flex w-full rounded-md border border-line p-0.5 text-xs font-medium">
      <AgentTab label="Claude" agent="claude" active={value === 'claude'} onClick={onChange} />
      <AgentTab label="Cursor" agent="cursor" active={value === 'cursor'} onClick={onChange} />
    </div>
  );
}

function AgentTab({
  label,
  agent,
  active,
  onClick,
}: {
  label: string;
  agent: Agent;
  active: boolean;
  onClick: (a: Agent) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onClick(agent)}
      className={`flex-1 rounded-[4px] py-1.5 transition-colors duration-fast ease-tool ${
        active ? 'bg-fg text-surface' : 'text-fg-muted hover:text-fg'
      }`}
    >
      {label}
    </button>
  );
}
