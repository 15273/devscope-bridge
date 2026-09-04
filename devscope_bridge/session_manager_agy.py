"""Antigravity CLI (`agy`) one-shot turns."""

from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path

from devscope_bridge import oneshot_runner
from devscope_bridge.agy_stream_parser import (
    activities_from_obj,
    parse_line_to_delta,
    session_id_from_text,
)
from devscope_bridge.mode_presets import MODE_PRESETS

logger = logging.getLogger(__name__)

_LOCAL = str(Path.home() / ".local" / "bin" / "agy")
_HOMEBREW = "/opt/homebrew/bin/agy"
_MISSING = (
    "agy not found. Install Antigravity CLI: "
    "curl -fsSL https://antigravity.google/cli/install.sh | bash"
)


def resolve_agy_bin() -> str | None:
    env = os.environ.get("AGY_BIN")
    if env:
        return env if os.path.exists(env) else None
    which = shutil.which("agy")
    if which:
        return which
    for path in (_LOCAL, _HOMEBREW):
        if os.path.exists(path):
            return path
    return None


def default_cli_root() -> Path:
    return Path.home() / ".gemini" / "antigravity-cli"


def _conversation_ids(root: Path) -> set[str]:
    conv = root / "conversations"
    if not conv.is_dir():
        return set()
    return {p.stem for p in conv.iterdir() if p.suffix in (".pb", ".json") or p.is_dir()}


def _newest_history_id(root: Path) -> str | None:
    hist = root / "history.jsonl"
    if not hist.is_file():
        return None
    last = None
    try:
        for line in hist.read_text(errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            cid = obj.get("conversationId") or obj.get("conversation_id")
            if isinstance(cid, str) and cid:
                last = cid
    except OSError:
        return None
    return last


class AgyBackend:
    agent = "antigravity"

    def resolve_bin(self) -> str | None:
        return resolve_agy_bin()

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
        cmd = [binary, "-p"]
        if os.environ.get("DEVSCOPE_AGY_PLAIN") != "1":
            cmd += ["--output-format", "stream-json"]
        if prior_session_id:
            cmd += [f"--conversation={prior_session_id}"]
        if model:
            cmd += ["--model", model]
        extra = (MODE_PRESETS.get(mode or "act") or {}).get("agy_extra_args") or []
        cmd += list(extra)
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
        root = default_cli_root()
        return {"ids": _conversation_ids(root), "root": str(root)}

    def recover_session_id(self, capture, stdout_lines, stderr, cwd) -> str | None:
        blob = "\n".join(stdout_lines) + "\n" + (stderr or "")
        from_text = session_id_from_text(blob)
        if from_text:
            return from_text
        root = Path((capture or {}).get("root") or default_cli_root())
        before = set((capture or {}).get("ids") or [])
        after = _conversation_ids(root)
        new = after - before
        if len(new) == 1:
            return next(iter(new))
        return _newest_history_id(root)


async def dispatch_agy(
    name: str,
    prompt: str,
    prior_session_id: str | None,
    cwd: str,
    mode: str | None = None,
    model: str | None = None,
):
    return await oneshot_runner.dispatch(
        name, prompt, prior_session_id, cwd, AgyBackend(),
        mode=mode, model=model,
    )
