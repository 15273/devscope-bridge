# DevScope roadmap — closing the gap with leading computer agents

DevScope is a **local-first** Chrome side panel plus a loopback bridge
(`127.0.0.1:7878`). An agent already talks to real tabs through
`POST /actions` and the `browser-control` MCP server: snapshots with
stable `@ref`s, click/fill, screenshots, console, network, and
named daily/QA Chrome profiles with a token-auth CDP fallback when the
side panel is closed.

The product goal is an **autonomous computer agent** — the best
developer extension and the best local agent on the market — without
giving up the security model (loopback only, token file `0600`, no
cloud backend).

## How the leaders compare

| Capability | DevScope today | Claude computer use / Claude for Chrome | OpenAI Operator / Atlas | Browser Use | Playwright MCP | Chrome DevTools MCP | Stagehand |
|---|---|---|---|---|---|---|---|
| Local / no cloud required | Yes (loopback) | No — Anthropic hosts the computer-use loop | No — OpenAI hosts Operator | Optional; default is a remote or local browser driver | Yes, if you run it | Yes, if you run it | Mostly local, LLM-backed |
| MCP tool surface | Yes (`browser-control` and other local MCP servers) | Claude Desktop MCP / Chrome extension, not a generic MCP you host | Not the public MCP path | Community wrappers | **The** Playwright MCP | **The** official Chrome DevTools MCP | Integrations, not a first-class MCP product |
| Accessibility-tree snapshots + stable refs | Yes (`browser_snapshot` + `@ref` click/fill) | Screenshot + coordinate or Chrome's a11y in Claude for Chrome | Mostly screenshots / DOM | DOM + a11y, selectors often regenerated | Playwright locators, role/text | DevTools a11y / DOM debugger | A11y-first, refs in their act/extract layer |
| Self-healing selectors when the DOM shifts | Partial (refs from the last snapshot; no retry/heal) | Relies on a new screenshot / model pass | Relies on a new visual pass | Built-in retry / selector repair | Auto-waiting, not LLM heal | Manual or scripted | **Core pitch**: act() heals locators |
| Observe → act → verify task loop | **`browser_run_steps`** (plan + verify + retry). The agent still supplies the plan. | Full hosted loop with the model in the middle | Full hosted loop, including check-out / booking flows | Agent loop with success criteria | You write the loop | You write the loop | `act` / `extract` / `observe` as a loop |
| Multi-profile / QA + daily browsers | Named `daily` / `qa` CDP + WS fan-out | Usually one signed-in Chrome | One Operator environment | Configurable contexts | One Playwright browser / context unless you add more | Attaches to one debug port | One browser |
| Console + network, filterable by tab / time | Yes (`tab_id`, `since_ts`) | Limited in the extension UI | Limited | Via the driver | Playwright tracing | DevTools panels, first-class | Limited |
| Drive Chrome when the panel is closed | Token-auth CDP fallback (subset of tools) | Extension must be available | Hosted browser | Driver owns the browser | Playwright owns the browser | CDP is the product | Driver owns the browser |
| Safety (no surprise submits, loopback, token redaction) | Explicit: loopback bind, token redaction, task loop refuses submit | User-in-the-loop confirms | User confirms purchases | You configure it | You configure it | You configure it | You configure it |

Sources for positioning (not a claim that we copied them):
[Claude computer use](https://www.anthropic.com/news/claude-3-5-sonnet),
[Claude for Chrome](https://www.anthropic.com/news/claude-for-chrome),
[OpenAI Operator](https://openai.com/index/introducing-operator/),
[Browser Use](https://github.com/browser-use/browser-use),
[Playwright MCP](https://github.com/microsoft/playwright-mcp),
[Chrome DevTools MCP](https://github.com/ChromeDevTools/chrome-devtools-mcp),
[Stagehand](https://github.com/browserbase/stagehand).

## What they still do that we don't

1. **A model-in-the-loop planner** that proposes the next step from a snapshot,
   instead of requiring the caller to pre-author `steps`.
2. **Self-healing locators** when a `@ref` or CSS selector goes stale mid-task
   (Stagehand / Browser Use).
3. **Richer CDP coverage** on the fallback path (input dispatch, downloads,
   dialogs, iframe targets) closer to Playwright MCP and Chrome DevTools MCP.
4. **Visual / screenshot-grounded click** when the a11y tree is empty.
5. **Hosted multi-hour unattended runs** (Operator). We will not host a cloud
   browser; we should instead make local unattended runs reliable.

## Top 3 to build next (autonomy + reliability)

1. **Verified task loop** — `browser_run_steps` (implemented). Observe / act /
   verify, retry on failure, refuse submit. This is the smallest complete
   autonomy primitive and the one every leading agent actually uses.
2. **Self-healing selectors** — when a `@ref` or selector misses, re-snapshot,
   match by role+name, and retry the action before failing the step.
3. **Richer CDP fallback + planner hook** — expand the no-panel path to the
   full tool set, and optionally let a local model propose steps from a
   snapshot (still executed through the verified loop, still loopback-only).

Work lands as small PRs on `main`. Do not weaken loopback or token auth.
