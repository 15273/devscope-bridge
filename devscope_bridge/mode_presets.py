"""
mode_presets.py — Maps AgentMode to claude CLI extra args + system-prompt suffix.

Flags verified against `claude --help` (2026-05-29):
  --permission-mode (choices: acceptEdits, auto, bypassPermissions, default, dontAsk, plan)
  --allowed-tools / --disallowed-tools
  --append-system-prompt
  --model

NOTE: never combine `--permission-mode` with `--dangerously-skip-permissions`
(claude rejects it). Permission behaviour comes solely from `--permission-mode`:
act/test/inspect use `bypassPermissions` (run tools without prompts), and
inspect additionally restricts the toolset via `--allowed-tools` to read-only
file + browser tools. plan uses `--permission-mode plan`.

Cursor CLI note: Cursor exposes `--mode=plan` and `--mode=ask`. We map:
  act     → (default, no mode flag — Cursor --print --trust is already permissive)
  plan    → --mode=plan
  inspect → --mode=ask  (closest read-only analogue in Cursor)
  test    → (default, system-prompt only)
"""

from typing import TypedDict


class ModePreset(TypedDict):
    # Extra args to append to the claude / cursor argv list.
    claude_args: list[str]
    cursor_args: list[str]
    # Text appended via --append-system-prompt (empty string → omit flag).
    system_prompt_suffix: str


# ---------------------------------------------------------------------------
# Mode → preset mapping
# ---------------------------------------------------------------------------

# Each value's claude_args are placed AFTER the fixed base args in
# session_manager._build_claude_args so they override base behaviour.

MODE_PRESETS: dict[str, ModePreset] = {
    "act": ModePreset(
        # bypassPermissions is equivalent to --dangerously-skip-permissions
        # and is already the base behaviour; kept explicit so a mode change
        # from plan/inspect back to act restores it correctly.
        claude_args=["--permission-mode", "bypassPermissions"],
        cursor_args=[],
        system_prompt_suffix=(
            "Proceed autonomously on implementation (run tools, edit files) without "
            "asking for confirmation on each step. When the user must pick between "
            "concrete options, use AskUserQuestion so the UI shows choice cards — "
            "do not only list numbered options in plain text."
        ),
    ),
    "plan": ModePreset(
        claude_args=["--permission-mode", "plan"],
        cursor_args=["--mode", "plan"],
        system_prompt_suffix=(
            "Produce a numbered plan and STOP. "
            "Do not edit files or run tools until the user explicitly says to proceed."
        ),
    ),
    "inspect": ModePreset(
        # Read-only: bypass prompts but restrict to read tools + the read-only
        # browser MCP tools (so the agent CAN inspect the page, but not edit
        # files or navigate/click). MCP tools are named mcp__<server>__<tool>.
        claude_args=[
            "--permission-mode", "bypassPermissions",
            "--allowed-tools",
            (
                "Read,Grep,Glob,WebFetch,"
                "mcp__browser-control__browser_snapshot,"
                "mcp__browser-control__browser_get_elements,"
                "mcp__browser-control__browser_get_page_info,"
                "mcp__browser-control__browser_list_tabs,"
                "mcp__browser-control__browser_screenshot,"
                "mcp__browser-control__browser_get_console,"
                "mcp__browser-control__browser_get_network,"
                "mcp__browser-control__browser_highlight"
            ),
        ],
        cursor_args=["--mode", "ask"],
        system_prompt_suffix=(
            "You are in Inspect mode: read-only exploration only. "
            "Never edit files. For the live page use read-only browser MCP tools only "
            "(browser_snapshot, browser_list_tabs, browser_get_page_info, browser_screenshot). "
            "Output your findings in a structured report."
        ),
    ),
    "test": ModePreset(
        # Test mode walks the live app, so it needs the full browser tool set.
        claude_args=["--permission-mode", "bypassPermissions"],
        cursor_args=[],
        system_prompt_suffix=(
            "You are in Test mode. Walk the live app: fill forms, click buttons, "
            "verify user flows. Write a structured test report (pass/fail per step), "
            "then generate a Playwright test that reproduces the exact sequence. "
            "Stop when done."
        ),
    ),
}

VALID_MODES = frozenset(MODE_PRESETS)

# Injected for Cursor sessions so the agent uses browser-control MCP (parity with Claude).
CURSOR_BROWSER_POLICY = (
    "BROWSER (DevScope): The browser-control MCP server is connected to the user's "
    "Chrome via the DevScope extension. When [BROWSER TAB BOUND] appears in the "
    "message, you MUST use browser_list_tabs, browser_snapshot, browser_get_page_info, "
    "browser_click, browser_fill, etc. Omit tab_id to control the bound tab. "
    "Do NOT call browser_focus_tab unless the user asks to see the page. "
    "For new pages use browser_new_page (opens in background by default) and bind that tab. "
    "Never navigate/click the user's personal active tab when a bound agent tab exists. "
    "Do NOT say you cannot access the browser — invoke these MCP tools first."
)

CURSOR_BROWSER_HINT = (
    "BROWSER (DevScope): browser-control MCP is available (browser_list_tabs, "
    "browser_snapshot, …). Use browser_new_page for new URLs (background tab), bind it, "
    "and automate there without calling browser_focus_tab."
)


def cursor_browser_prompt_suffix(
    *,
    has_bound_tab: bool,
    mode: str | None,
) -> str:
    """Extra system text for Cursor when page/browser context matters."""
    if has_bound_tab:
        return CURSOR_BROWSER_POLICY
    if mode in ("test", "inspect", "act"):
        return CURSOR_BROWSER_HINT
    return ""
