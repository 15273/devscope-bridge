## What this changes

<!-- One or two sentences. Link the issue if there is one. -->

## Why

<!-- What was wrong or missing. -->

## Checklist

- [ ] `pytest` passes (`source .venv/bin/activate && pytest`)
- [ ] Behavior change → a test covers it. Refactor → existing tests still pass.
- [ ] Extension touched → `npm run build` and `npm run lint` pass in `extension/`
- [ ] No new dependency, or the PR body explains why it's needed

## Security model

The bridge binds loopback only, auth is the local token file, and there is no
cloud backend. Confirm this PR:

- [ ] Does not add a non-loopback bind or bypass `_assert_loopback_host`
- [ ] Does not disable or weaken the token check
- [ ] Does not send anything off the machine
- [ ] Keeps `workers=1` semantics (PTYs and WebSockets live in one process)

<!-- If a box above can't be ticked, say so here and explain. Better to
     discuss it in the open than to have the PR closed on sight. -->

## Autonomy policy

- [ ] N/A — this PR doesn't touch the orchestrator or worker prompts
- [ ] This PR changes what an unattended agent may do without approval, and the
      PR body explains the new boundary (see `agent_policies.py`)
