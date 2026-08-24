"""The appended system prompt must tell the agent to switch tools on failure.

Regression for the stuck-browser-turn bug: sessions kept retrying a hanging
MCP tool (playwright in --extension mode) for 900s until the watchdog killed
the turn, instead of falling back to another browser tool (browser-control /
WebFetch).
"""
from devscope_bridge import session_lifecycle as sl


def _appended_prompt(args: list[str]) -> str:
    idx = args.index("--append-system-prompt")
    return args[idx + 1]


def test_act_mode_prompt_includes_tool_fallback_guidance():
    prompt = _appended_prompt(sl._build_claude_args(None, mode="act"))
    assert "different tool" in prompt


def test_fallback_guidance_names_browser_control():
    prompt = _appended_prompt(sl._build_claude_args(None, mode="act"))
    assert "browser-control" in prompt
