# Chrome Web Store — Screenshot Guidance

Chrome Web Store screenshots are **1280×800 PNG** (or JPEG). Provide 4–5. Order
matters: the first screenshot is the hero shown largest in search results, so it
must communicate the core value in one glance.

Visual conventions for all shots:
- Compose the real Chrome side panel (DevScope) docked on the right, over a
  realistic developer-context page on the left (docs, a dashboard, or the app
  under development). The page on the left provides context; DevScope is the hero.
- Use the Graphite design language: warm amber signal accent (`#FB923C` in dark,
  `#E86D13` in light). Inter for UI text, JetBrains Mono for code.
- Keep the connection pip in the header green ("connected") so the product looks live.
- No Lorem Ipsum and no fake metrics — use believable real developer content.
- Optional: a thin amber caption bar along the top or bottom with the one-liner,
  consistent across all shots. Keep the actual UI unobstructed.

## Shot 1 — Active chat (dark mode) — HERO

Show a live session: the user asked a real coding question, and the agent's reply
is streaming in with Markdown and a syntax-highlighted code block visible. Header
shows the DevScope reticle logomark, session name, and the green connection pip.

Caption: "Your local Claude or Cursor agent, one keystroke away in the side panel."

## Shot 2 — Agent acting on the live page

Show the agent mid-task on the page in the left pane — e.g. a tool call that
inspected/filled a form or navigated the tab — with the result reflected on the
page and an agent/tool badge visible in the transcript.

Caption: "Ask it to read, click, fill, or screenshot the page you're looking at."

## Shot 3 — Onboarding / connect flow

Show the first-run Onboarding screen: the reticle logomark, "Let's connect
DevScope", the two copy-pasteable setup steps (`pipx install devscope-bridge`
then `devscope-bridge`), and the status row.

Caption: "Three steps to connect — install the local bridge, start it, paste your token."

## Shot 4 — Toolbar / browser action entry point

Show the Chrome toolbar with the amber DevScope reticle icon and its tooltip
("Open DevScope"), with the side panel opening alongside.

Caption: "One click from the toolbar opens DevScope beside any tab."

## Shot 5 — Code rendering & light mode (settings)

Show DevScope in light mode: a message with a richly rendered fenced code block
(language label, copy button, monospaced JetBrains Mono), and the Settings panel
or theme toggle visible to demonstrate polish in both themes.

Caption: "Polished light and dark themes, with first-class code rendering."
