/**
 * Glossary — searchable in-app dictionary of DevScope concepts, so a new user
 * can understand what the tool can do. Reachable via the `?` button and `/help`.
 */
import { useMemo, useState } from 'react';
import { ArrowLeft, Search } from 'lucide-react';

interface SettingsLikeProps {
  onClose: () => void;
}

interface Term {
  term: string;
  def: string;
}

const TERMS: Term[] = [
  { term: 'Bridge', def: 'The small local server (devscope-bridge) on your machine that runs your Claude/Cursor CLI and connects it to this extension. Your code never leaves your machine.' },
  { term: 'Session', def: 'One conversation with the agent, tied to a single project directory. Switch between sessions in the sidebar.' },
  { term: 'Project', def: 'A folder on disk. Each session runs the agent inside its project, with access to that codebase.' },
  { term: 'Token', def: 'The auth secret that links this extension to your bridge. Printed when the bridge starts; paste it in Settings.' },
  { term: 'Mode', def: 'How Claude behaves: Act, Plan, Inspect, or Test. Controls when it asks vs runs alone — not which browser tab is used.' },
  { term: 'Act mode', def: 'Runs autonomously with all tools. Asks only via AskUserQuestion cards (structured choices in chat).' },
  { term: 'Plan mode', def: 'Writes a numbered plan and stops. You must Approve before any file edits or execution.' },
  { term: 'Inspect mode', def: 'Read-only: snapshot, grep, explain. No navigation clicks and no file edits.' },
  { term: 'Test mode', def: 'Walks the live tab (click, fill), reports pass/fail, can draft Playwright tests. Same autonomy as Act.' },
  { term: 'Browse backend', def: 'How tools reach your page: This tab (extension scripts), CDP (DevTools on the same tab), or Auto (pick per action). Never a separate browser.' },
  { term: 'Element picker', def: 'Click “Pick element”, then click anything on the page. Its selector and details attach to your message as a chip.' },
  { term: 'Context chip', def: 'An attached element or slice of page state shown above the input and sent to the agent with your message.' },
  { term: 'Snapshot', def: 'A compact, accessibility-style view of the page (roles, names, selectors) — cheaper for the agent than full HTML.' },
  { term: 'Screenshot', def: 'An image of the visible page you can attach as context.' },
  { term: 'Console / Network', def: 'Captured browser console output and network requests you can attach so the agent can debug.' },
  { term: 'Browser tools', def: 'Actions the agent can run on the live page itself: click, fill, navigate, screenshot, wait, assert, and more.' },
  { term: '/cursor-ctx', def: 'Cursor scouts the codebase read-only (paths, symbols, data flow), then Claude runs your task with that map. Usage: /cursor-ctx <task>. Alias: /ctx. Claude sessions only.' },
  { term: '/cursor-task', def: 'Run Cursor with MCP plugins (Notion, browser, tasks, calendar, …) in a parallel bubble. Works on Claude or Cursor sessions. Usage: /cursor-task <task>. Aliases: /plugins, /notion.' },
  { term: 'Cursor session', def: 'DevScope session where the agent is cursor-agent instead of Claude. Has access to .cursor/mcp.json tools for the whole conversation. Create via New chat → Agent: Cursor.' },
  { term: 'Cursor MCP plugins', def: 'Tools configured in .cursor/mcp.json plus Cursor-account plugins (Notion, etc.). Available in Cursor sessions or via /cursor-task. One-time setup: cursor-agent mcp list (all should show ready).' },
  { term: '/ask', def: 'Parallel side-query — a short Claude answer in its own bubble without stopping the main turn. Usage: /ask <question>.' },
  { term: 'Slash command', def: 'Type “/” for quick commands: switch modes, attach page state, open help, or run your own .claude/commands.' },
  { term: '/usage (also /cost, /context)', def: 'Show token usage and estimated cost accumulated in the current session, broken down by input/output/cache tokens.' },
  { term: '/compact', def: 'Summarise the conversation and start a fresh CLI session with the summary injected as preamble. Chat history in the panel is preserved. Usage: /compact [extra instructions]' },
  { term: '/new', def: 'Start a completely fresh CLI conversation. Chat history in the panel is preserved. Use /clear to clear attached context chips instead.' },
  { term: '/clear vs /new', def: '/clear removes attached context chips (screenshots, snapshots, elements) from the composer. /new starts a fresh Claude conversation. These are intentionally separate.' },
  { term: '/model', def: 'Show or switch the Claude model. Prefer the model pill next to Act/Plan — or /model <name>. Takes effect on the next message.' },
  { term: '/memory', def: 'Display what context files are loaded: CLAUDE.md (project instructions) and the user memory index from ~/.claude.' },
  { term: '/status', def: 'Show the active model, session ID, mode, CWD, and CLI version — all from bridge metadata, no model turn needed.' },
  { term: '/add-dir <path>', def: 'Persist an extra working directory in the session metadata. The path must exist on disk. Takes effect on the next message (session respawns). --add-dir spawn-wiring is a follow-up step.' },
  { term: '/review [focus]', def: 'Ask Claude to review the current git diff for bugs, logic errors, and risky changes. Runs git diff / git diff --staged in your session cwd. Optionally append a focus area.' },
  { term: '/security-review [focus]', def: 'Security review of the current git diff: injection, authz/authn, secrets, SSRF, path traversal. Cites file:line and severity (high/medium/low).' },
  { term: '/pr-comments [PR#]', def: 'Fetch and summarise unresolved code-review comments on the current PR (or the PR# you provide). Groups by file; gives actionable items. Requires gh CLI.' },
  { term: '/export', def: 'Export the current chat panel to a Markdown file and download it. Includes user/assistant turns and slash-card bodies as fenced blocks. Pure frontend — no bridge call.' },
  { term: 'Alias searchability', def: 'Typing /cost or /context in the slash menu now reveals the /usage entry. Aliases match without creating duplicate rows.' },
  { term: 'Terminal-only commands', def: 'Some commands (/doctor, /diff, /vim, /ide, etc.) only work in an interactive terminal session. They appear greyed-out in the menu with a “terminal only” label.' },
  { term: 'Tool-call log', def: 'The ⚙ rows in the chat showing each browser action the agent took, with success/failure.' },
  { term: 'MCP', def: 'Model Context Protocol — the standard that exposes the browser tools to your local agent through the bridge.' },
];

export function Glossary({ onClose }: SettingsLikeProps) {
  const [query, setQuery] = useState('');
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return TERMS;
    return TERMS.filter((t) => t.term.toLowerCase().includes(q) || t.def.toLowerCase().includes(q));
  }, [query]);

  return (
    <div className="flex h-full flex-1 flex-col overflow-hidden bg-surface">
      <div className="flex items-center gap-2 border-b border-line bg-surface-raised px-3 py-2.5">
        <button
          onClick={onClose}
          aria-label="Back"
          className="rounded-md p-1 text-fg-subtle transition-colors duration-fast ease-tool hover:bg-surface-overlay hover:text-fg"
        >
          <ArrowLeft size={16} strokeWidth={2} />
        </button>
        <span className="text-sm font-semibold text-fg">Glossary</span>
      </div>

      <div className="border-b border-line px-3 py-2">
        <div className="flex items-center gap-2 rounded-md border border-line bg-surface-overlay px-2.5 py-1.5">
          <Search size={14} strokeWidth={2} className="flex-shrink-0 text-fg-subtle" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search terms…"
            className="w-full bg-transparent text-sm text-fg placeholder-fg-subtle outline-none"
            aria-label="Search glossary"
          />
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-3">
        {filtered.length === 0 ? (
          <p className="py-6 text-center text-xs text-fg-subtle">No matching terms.</p>
        ) : (
          <dl className="space-y-3">
            {filtered.map((t) => (
              <div key={t.term}>
                <dt className="text-xs font-semibold text-fg">{t.term}</dt>
                <dd className="mt-0.5 text-xs leading-relaxed text-fg-muted">{t.def}</dd>
              </div>
            ))}
          </dl>
        )}
      </div>
    </div>
  );
}
