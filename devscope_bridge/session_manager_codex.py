"""Codex CLI — exec --json one-shot, with optional app-server upgrade."""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

from devscope_bridge import oneshot_runner
from devscope_bridge.codex_stream_parser import activities_from_obj, parse_line_to_delta
from devscope_bridge.mode_presets import MODE_PRESETS

logger = logging.getLogger(__name__)

_HOMEBREW = "/opt/homebrew/bin/codex"
_LOCAL = str(Path.home() / ".local" / "bin" / "codex")
_CHATGPT_APP = "/Applications/ChatGPT.app/Contents/Resources/codex"


def resolve_codex_bin() -> str | None:
    env = os.environ.get("CODEX_BIN")
    if env:
        return env if os.path.exists(env) else None
    which = shutil.which("codex")
    if which:
        return which
    for path in (_HOMEBREW, _LOCAL, _CHATGPT_APP):
        if os.path.exists(path):
            return path
    return None


def _sandbox_for_mode(mode: str | None) -> str:
    preset = MODE_PRESETS.get(mode or "act") or {}
    return str(preset.get("codex_sandbox") or "workspace-write")


class CodexExecBackend:
    agent = "codex"

    def resolve_bin(self) -> str | None:
        return resolve_codex_bin()

    def missing_bin_message(self) -> str:
        return (
            "codex not found. Install with: brew install --cask codex "
            "or curl -fsSL https://chatgpt.com/codex/install.sh | sh"
        )

    def build_cmd(
        self,
        binary: str,
        prompt: str,
        prior_session_id: str | None,
        mode: str | None,
        model: str | None,
        cwd: str,
    ) -> list[str]:
        sandbox = _sandbox_for_mode(mode)
        if prior_session_id:
            cmd = [binary, "exec", "resume", prior_session_id, "--json"]
        else:
            cmd = [binary, "exec", "--json", "-C", cwd, "-s", sandbox]
        if model:
            cmd += ["-m", model]
        preset = MODE_PRESETS.get(mode or "act")
        if preset and preset.get("system_prompt_suffix") and (mode or "act") != "act":
            prompt = preset["system_prompt_suffix"] + "\n\n" + prompt
        cmd.append(prompt)
        return cmd

    def parse_line(self, line: str, accum: str):
        return parse_line_to_delta(line, accum)

    def activities_from_obj(self, obj: dict):
        return activities_from_obj(obj)

    def env(self, session_name: str, cwd: str) -> dict[str, str]:
        return oneshot_runner.default_env(session_name, cwd)

    def capture_before(self, cwd: str):
        return None

    def recover_session_id(self, capture, stdout_lines, stderr, cwd) -> str | None:
        return None


async def dispatch_codex(
    name: str,
    prompt: str,
    prior_session_id: str | None,
    cwd: str,
    mode: str | None = None,
    model: str | None = None,
):
    if os.environ.get("DEVSCOPE_CODEX_EXEC_ONLY") != "1":
        try:
            from devscope_bridge import codex_app_server
            if codex_app_server.app_server_available():
                return await codex_app_server.dispatch(
                    name, prompt, prior_session_id, cwd, mode=mode, model=model,
                )
        except Exception as exc:
            logger.warning("codex app-server unavailable, falling back to exec: %s", exc)
    return await oneshot_runner.dispatch(
        name, prompt, prior_session_id, cwd, CodexExecBackend(),
        mode=mode, model=model,
    )
