# Contributing

Small project, small process. PRs welcome.

## Dev setup

Bridge (Python 3.11+):

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
pip install pytest
```

Extension (Node 18+):

```bash
cd extension
npm install
npm run build        # or: npm run dev (watch mode)
npm run lint         # tsc --noEmit
```

Load `extension/dist/` unpacked in Chrome. Full setup is in the README.

## Tests

```bash
source .venv/bin/activate
pytest
```

Tests that spawn a real `claude` process are skipped unless `RUN_EMPIRICAL=1`.
Don't gate normal tests on it — most contributors won't have the CLI logged in
in CI.

## PRs

- Behavior change → test that covers it. Refactors don't need new tests, but
  `pytest` must still pass.
- **Do not weaken the security model.** The bridge binds loopback only
  (`_assert_loopback_host` in `devscope_bridge/main.py`), auth is the local
  token file (`~/.dev-bridge/token`, chmod 0600), and there is no cloud
  backend. PRs that add a non-loopback bind, disable token checks, or phone
  home will be closed.
- Keep `workers=1` semantics — PTYs and WebSockets live in one process.
- Match the existing style; no new dependencies without a reason in the PR
  description.
- Small, focused PRs review faster than big ones.
