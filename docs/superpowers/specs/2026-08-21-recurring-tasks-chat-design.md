# Recurring Tasks as Employees — Chat-First Redesign

**Date:** 2026-08-21
**Status:** Approved (user chose full rebuild, approach: evolve existing rails)

## Vision

A recurring task is an **employee**: it has a dedicated chat you talk to, a home
directory with persistent memory and accumulating deliverables, a defined
autonomy policy, and it runs on schedule in fresh sessions. The user experience
is conversational end to end — creating a task is a chat, checking on a task is
a chat, answering its questions is a chat. Hebrew-first UI, human tone.

User decisions captured:

1. Rebuild end to end (creation UX + execution + management were all broken).
2. Dedicated chat per task. Runs do NOT accumulate in the chat as transcripts —
   each run is a fresh session; the chat shows a short human digest per run.
3. After each run: short digest message in the task chat + a persisted,
   accumulating report/artifact in the task's home (`reports/`).
4. Important questions pause the run and wait for the user in the task chat.
   Routine stuck questions are answered by a periodic **chief agent** sweep.
   Each task carries a free-text autonomy policy defining the boundary.
5. Engine per task: `claude` or `cursor` (routing must actually work).

## Current state (mapped 2026-08-21)

- Creation: `NewScheduleModal.tsx` 3-step wizard (מטרה/מיפוי/סיום). A partial
  "setup chat" exists (`POST /schedules/setup/start`, session
  `purpose: 'schedule_setup'`) but dead-ends: no way to commit a schedule from
  chat; drafts are one global `active.json`.
- Storage: SQLite `schedules` table (`task_store.py:62`) with `template_json`
  (title, instruction, domain, autonomy e2e|guarded, agent, mode, recurrence)
  and `playbook_json` (site, entry_urls, workflow, selectors, notes, …).
- Execution: `orchestrator.py` asyncio loop, default tick 720s;
  `materialise_due_schedules` creates a task routed through MoM triage →
  manager → `_dispatch_worker` → `worker-{task_id}` session.
- Known breakage (must fix):
  1. **Browser 503 race** — `browser_relay.py:376-386` targets the exact
     `worker-*` session WS, which the extension opens only while the panel is
     open and has observed `turnRunning`. Scheduled browser automation fails
     closed.
  2. **Cursor routing is cosmetic** — `session_runner.py:57` ignores the
     schedule's `agent` and uses the stored session agent (always claude).
  3. **No run history** — no runs list/status/logs anywhere in the UI.
  4. **Timing drift** — 12-min tick, next_run computed from tick time,
     string-compared timestamps.
  5. Misc: `cron_expr` dead, single global setup draft, selectors edited as raw
     JSON, no delete/run-now buttons, `schedule_discover.py` dead code +
     session-name bug in `cockpit_agent._run_claude`.

## Design

### 1. Data model

`schedules` table stays; template gains:

- `autonomy_policy: str` — free-text Hebrew policy written during setup, e.g.
  "מותר לאסוף מידע ולנווט; כל פעולה שכותבת לפרודקשן — לעצור ולשאול". Quoted to
  the chief agent and injected into every run prompt.
- Existing `agent: claude|cursor` kept, now honored.

**Task home** `~/.dev-bridge/task_homes/{schedule_id}/`:

- `MEMORY.md` — curated persistent memory. Injected into every run's prompt;
  the run agent updates it via MCP tool at end of run.
- `reports/` — accumulating deliverables (the per-run artifact / evolving
  report). Files listed in the task chat digest with open/download affordance.

**New table `schedule_runs`:**

```
id, schedule_id, task_id, started_at, finished_at,
status: running|success|failed|waiting_user|answered_by_chief,
digest_text,            -- the short human summary shown in chat
question_text,          -- set when waiting_user
question_importance,    -- routine|important (agent-classified vs policy)
answered_by, answer_text,
artifacts_json,         -- list of files created under reports/
log_session             -- worker session name for drill-down
```

**Pending questions** are `schedule_runs` rows with `status=waiting_user`.

### 2. Chat-first creation (modal removed)

"משימה חדשה" opens a normal chat session (`purpose: 'schedule_setup'`) with a
setup agent. The agent interviews naturally (what, when, which sites, engine,
autonomy boundaries), maintains a draft, and the panel renders a live **draft
card** above the composer (title, schedule, engine, autonomy) that updates as
the conversation progresses. The user commits with words ("סגור, תתחילי מחר");
the agent calls a new `schedule_commit` MCP tool → `POST /schedules` server-side.

- New/extended MCP tools on the setup session: `schedule_setup_update` (exists),
  plus setters for recurrence, engine, autonomy_policy, and `schedule_commit`.
- Drafts become per-session files (`schedule_setups/{session}.json`), killing
  the global `active.json` clobber.
- `NewScheduleModal.tsx` is deleted; the "+ תזמון" button starts the chat.

### 3. Per-task chat (the employee's office)

Schedules tab → list of employees (name, next run, last digest snippet, status
dot: ok / failed / waiting-for-you). Opening one shows a **feed**, not a raw
transcript:

- Run digest messages (from `schedule_runs.digest_text`) with timestamp,
  status, artifact chips, and a "פתח לוג מלא" drill-down that opens the worker
  session read-only.
- Question cards when `waiting_user` — answering in the chat resumes the run
  (answer is delivered to the paused worker session or spawns a resume run).
- Free chat: the user can talk to the task any time. Messages go to a
  **steward session** per schedule (`steward-{id}`, fresh-ish, cheap) whose
  context = template + MEMORY.md + recent digests. The steward can adjust the
  schedule (via MCP tools), update memory, answer "מה קרה לאחרונה", or trigger
  "run now".
- Management actions as chat-adjacent buttons: הרץ עכשיו, השהה, מחק (wired to
  the existing dead endpoints + new `POST /schedules/{id}/run`).

### 4. Run pipeline

- Each due schedule creates a fresh worker run (as today) with prompt =
  instruction + playbook + MEMORY.md + autonomy_policy + digest-format contract.
- End of run, the agent MUST call `schedule_run_report` MCP tool: digest text,
  artifacts written, memory updates. Missing report → bridge synthesizes a
  fallback digest from the transcript tail and marks it degraded.
- **Browser fix:** scheduled/background runs may target any live extension WS
  in the right Chrome profile — `browser_relay._target_session` gets a fallback
  for `worker-*`/background sessions instead of failing 503 on exact-name miss.
  (Panel does not need to be open on the worker session.)
- **Cursor fix:** `session_runner.run_turn` passes `agent` through to session
  creation AND overrides the stored agent for schedule-driven runs.
- **Timing fix:** next_run computed from the scheduled time (not tick time),
  datetime comparison instead of string, tick default lowered (60s) with due
  check cheap; recurrence gains `weekly_at` alongside `every_minutes`/`daily_at`.

### 5. Chief agent sweep

Runs inside the existing orchestrator tick (separate cadence, e.g. every tick):
finds `schedule_runs` with `status=waiting_user`, and for each asks a small
Claude call: given the task's autonomy_policy + question, is this within the
task's own authority? If routine → answer it (resume run, mark
`answered_by_chief`, note the decision in the digest). If important → leave for
the user and (optionally) surface a notification. The user can also set a task
to "always wait" via the policy text.

### 6. Error handling

- Run crash / engine death → `schedule_runs.status=failed` + digest with the
  error in plain Hebrew; failure visible in list (red dot) and chat feed.
- Browser unavailable (no Chrome connected at all) → run fails fast with a
  clear digest ("הדפדפן לא היה מחובר"), retried next occurrence; no infinite
  hang.
- Chief agent never answers questions classified important; ties break toward
  waiting for the user.

### 7. Testing

- Python: unit tests for run-record lifecycle, next_run math (incl. drift),
  browser-relay fallback targeting, cursor routing, chief-agent classification
  plumbing (LLM call mocked), setup-draft per-session isolation.
- Extension: vitest for feed reducer/digest rendering and draft-card state;
  existing test conventions in `extension/src/sidepanel/utils/*.test.ts`.
- Manual E2E: create a task by chat, let it run, see digest + artifact, ask it
  a question, pause/resume/delete.

## Out of scope

- Multi-user/auth changes, mobile, non-Chrome browsers.
- Migrating old schedules beyond a best-effort template upgrade (existing rows
  keep working; missing new fields get defaults).
- `cron_expr` support (delete the dead column usage instead).
