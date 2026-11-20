"""Grok CLI (`grok -p`) and Grok Bot (`--always-approve`) one-shot turns."""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from pathlib import Path

from devscope_bridge import oneshot_runner
from devscope_bridge.grok_stream_parser import (
    activities_from_obj,
    parse_line_to_delta,
    session_id_from_obj,
    thoughts_from_obj,
)
from devscope_bridge.mode_presets import MODE_PRESETS

logger = logging.getLogger(__name__)

_HOMEBREW = "/opt/homebrew/bin/grok"
_LOCAL = str(Path.home() / ".local" / "bin" / "grok")
_MISSING = "grok not found. Install Grok CLI and run `grok login`."

# Same on-page DevScope mouse + screenshots Claude gets — Grok must call these MCP tools.
GROK_BROWSER_RULES = """You control the user's real Chrome via DevScope MCP server browser-control (not playwright, not chrome-devtools, unless they ask).
Tools: browser_list_tabs, browser_snapshot, browser_screenshot, browser_click, browser_fill, browser_evaluate, browser_new_page, browser_navigate, browser_wait_for_selector, browser_get_page_info.
When the user talks about a page, a bound tab, AWS, or "look at the browser":
1. Call browser_list_tabs. Prefer the tab with is_bound=true, else match the URL they mean.
2. browser_snapshot then browser_screenshot on that tab_id (or omit tab_id if bound).
3. Click/fill using snapshot @ref numbers. An orange DevScope mouse cursor moves on the page.
Never guess page content. If a tool says tab not found, list_tabs again and pass an explicit tab_id.
Do not call browser_focus_tab unless they ask to see the page."""



def resolve_grok_bin() -> str | None:
    env = os.environ.get("GROK_BIN")
    if env:
        return env if os.path.exists(env) else None
    which = shutil.which("grok")
    if which:
        return which
    for path in (_HOMEBREW, _LOCAL):
        if os.path.exists(path):
            return path
    return None


class GrokBackend:
    agent = "grok"
    always_approve = False

    def __init__(self) -> None:
        self._prompt_files: list[str] = []

    def resolve_bin(self) -> str | None:
        return resolve_grok_bin()

    def missing_bin_message(self) -> str:
        return _MISSING

    def build_cmd(
        self,
        binary: str,
        prompt: str,
        prior_session_id: str | None,
        mode: str | None,
        model: str | None,
        cwd: str,
    ) -> list[str]:
        cmd = [
            binary,
            "--output-format", "streaming-messages-json",
            "--include-partial-messages",
            "--cwd", cwd,
        ]
        if prior_session_id:
            cmd += ["--resume", prior_session_id]
        if model:
            cmd += ["-m", model]
        if self.always_approve:
            cmd += ["--always-approve"]
        else:
            perm = "plan" if (mode or "act") == "plan" else "bypassPermissions"
            if (mode or "act") == "inspect":
                perm = "default"
            cmd += ["--permission-mode", perm]
        cmd += ["--rules", GROK_BROWSER_RULES]
        preset = MODE_PRESETS.get(mode or "act")
        if preset and preset.get("system_prompt_suffix") and (mode or "act") != "act":
            prompt = preset["system_prompt_suffix"] + "\n\n" + prompt
        # Page context starts with "--- PAGE CONTEXT ---"; passing it as `-p`
        # makes clap treat it as a flag. --prompt-file keeps the full text.
        fd, path = tempfile.mkstemp(prefix="devscope-grok-", suffix=".txt")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(prompt)
        self._prompt_files.append(path)
        cmd += ["--prompt-file", path]
        return cmd

    def parse_line(self, line: str, accum: str):
        return parse_line_to_delta(line, accum)

    def activities_from_obj(self, obj: dict):
        return activities_from_obj(obj)

    def thoughts_from_obj(self, obj: dict) -> str | None:
        return thoughts_from_obj(obj)

    def env(self, session_name: str, cwd: str) -> dict[str, str]:
        env = oneshot_runner.default_env(session_name, cwd)
        import devscope_bridge

        root = Path(devscope_bridge.__file__).resolve().parent.parent
        venv_bin = root / ".venv" / "bin"
        path = env.get("PATH", "")
        if venv_bin.is_dir():
            env["PATH"] = str(venv_bin) + os.pathsep + path
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = str(root) + ((os.pathsep + existing) if existing else "")
        return env

    def capture_before(self, cwd: str):
        return None

    def cleanup_turn(self) -> None:
        for path in self._prompt_files:
            try:
                os.unlink(path)
            except OSError:
                pass
        self._prompt_files.clear()

    def recover_session_id(self, capture, stdout_lines, stderr, cwd) -> str | None:
        self.cleanup_turn()
        for line in reversed(stdout_lines):
            stripped = line.strip()
            if not stripped.startswith("{"):
                continue
            try:
                import json
                obj = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                sid = session_id_from_obj(obj)
                if sid:
                    return sid
        return None


class GrokBotBackend(GrokBackend):
    agent = "grok_bot"
    always_approve = True


async def dispatch_grok(
    name: str,
    prompt: str,
    prior_session_id: str | None,
    cwd: str,
    mode: str | None = None,
    model: str | None = None,
    *,
    bot: bool = False,
):
    backend: GrokBackend = GrokBotBackend() if bot else GrokBackend()
    return await oneshot_runner.dispatch(
        name, prompt, prior_session_id, cwd, backend,
        mode=mode, model=model,
    )
