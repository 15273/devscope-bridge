/**
 * NewTaskModal — creates a new autonomous orchestrator task (POST /tasks).
 * Fields: title, instruction, project (dropdown from saved paths), E2E toggle.
 */
import { useState, useEffect, useCallback, useRef, KeyboardEvent } from 'react';
import { X } from 'lucide-react';
import { createTask, type TaskAutonomy } from '../bridge';
import { loadProjectPaths } from '../utils/storage';

interface NewTaskModalProps {
  onClose: () => void;
}

export function NewTaskModal({ onClose }: NewTaskModalProps) {
  const [title, setTitle] = useState('');
  const [instruction, setInstruction] = useState('');
  const [projectPaths, setProjectPaths] = useState<string[]>([]);
  const [selectedPath, setSelectedPath] = useState('');
  const [e2e, setE2e] = useState(false);
  const [submitError, setSubmitError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const titleRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    loadProjectPaths()
      .then((paths) => {
        setProjectPaths(paths);
        if (paths.length > 0) setSelectedPath(paths[0]);
      })
      .catch(() => {});
    titleRef.current?.focus();
  }, []);

  useEffect(() => {
    function onKey(e: globalThis.KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const handleSubmit = useCallback(async () => {
    if (!title.trim()) {
      setSubmitError('Title is required');
      return;
    }
    setIsSubmitting(true);
    setSubmitError('');
    const autonomy: TaskAutonomy = e2e ? 'e2e' : 'guarded';
    try {
      await createTask({
        title: title.trim(),
        instruction: instruction.trim() || undefined,
        project_path: selectedPath || undefined,
        autonomy,
      });
      onClose();
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : 'Failed to create task');
    } finally {
      setIsSubmitting(false);
    }
  }, [title, instruction, selectedPath, e2e, onClose]);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLInputElement>) => {
      if (e.key === 'Enter' && !isSubmitting) handleSubmit();
    },
    [handleSubmit, isSubmitting],
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
        {/* Header */}
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-fg">New Task</h2>
          <button
            onClick={onClose}
            aria-label="Close"
            className="rounded-md p-1 text-fg-subtle transition-colors duration-fast ease-tool hover:bg-surface-raised hover:text-fg"
          >
            <X size={14} strokeWidth={2.5} />
          </button>
        </div>

        {/* Title */}
        <div className="mb-3">
          <label htmlFor="task-title" className="mb-1 block text-xs font-medium text-fg-muted">
            Title
          </label>
          <input
            id="task-title"
            ref={titleRef}
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="What should the agent do?"
            className="w-full rounded-md border border-line bg-surface px-3 py-2 text-sm text-fg outline-none transition-colors duration-fast ease-tool focus:border-signal"
          />
        </div>

        {/* Instruction */}
        <div className="mb-3">
          <label htmlFor="task-instruction" className="mb-1 block text-xs font-medium text-fg-muted">
            Instruction <span className="font-normal text-fg-subtle">(optional)</span>
          </label>
          <textarea
            id="task-instruction"
            rows={4}
            value={instruction}
            onChange={(e) => setInstruction(e.target.value)}
            placeholder="Precise steps, context, constraints…"
            className="w-full rounded-md border border-line bg-surface px-3 py-2 text-sm text-fg outline-none transition-colors duration-fast ease-tool focus:border-signal resize-none"
          />
        </div>

        {/* Project */}
        <div className="mb-3">
          <label htmlFor="task-project" className="mb-1 block text-xs font-medium text-fg-muted">
            Project
          </label>
          {projectPaths.length === 0 ? (
            <p className="text-xs text-fg-muted">
              No projects configured. <span className="text-signal">Add one in Settings →</span>
            </p>
          ) : (
            <select
              id="task-project"
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

        {/* E2E toggle */}
        <div className="mb-4 flex items-start gap-2.5 rounded-md border border-line bg-surface px-3 py-2.5">
          <input
            id="task-e2e"
            type="checkbox"
            checked={e2e}
            onChange={(e) => setE2e(e.target.checked)}
            className="mt-0.5 h-3.5 w-3.5 shrink-0 accent-signal"
          />
          <label htmlFor="task-e2e" className="cursor-pointer select-none">
            <span className="block text-xs font-semibold text-fg">End-to-end (autonomous)</span>
            <span className="mt-0.5 block text-xs leading-snug text-fg-muted">
              Runs send/delete without asking. Purchases and anything spending money still pause for
              approval.
            </span>
          </label>
        </div>

        {/* Error */}
        {submitError && (
          <p className="mb-3 rounded-md bg-danger-subtle px-3 py-2 text-xs text-danger">
            {submitError}
          </p>
        )}

        {/* Actions */}
        <div className="flex justify-end gap-2">
          <button
            onClick={onClose}
            disabled={isSubmitting}
            className="rounded-md px-4 py-2 text-sm text-fg-muted transition-colors duration-fast ease-tool hover:bg-surface-raised"
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={!title.trim() || isSubmitting}
            className="rounded-md bg-signal px-4 py-2 text-sm font-medium text-signal-contrast transition-colors duration-fast ease-tool hover:bg-signal-hover disabled:opacity-40"
          >
            {isSubmitting ? 'Creating…' : 'Create Task'}
          </button>
        </div>
      </div>
    </div>
  );
}
