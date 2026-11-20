from pathlib import Path

from devscope_bridge.agents import (
    VALID_AGENTS,
    keep_session_id_on_reset,
    parse_agent,
)
from devscope_bridge.session_manager_codex import CodexExecBackend
from devscope_bridge.session_manager_grok import GrokBackend, GrokBotBackend


def test_parse_agent():
    assert parse_agent("codex") == "codex"
    assert parse_agent("antigravity") == "antigravity"
    assert parse_agent("grok") == "grok"
    assert parse_agent("grok_bot") == "grok_bot"
    assert parse_agent("nope") == "claude"
    assert VALID_AGENTS == {"claude", "cursor", "codex", "antigravity", "grok", "grok_bot"}


def test_keep_id_on_reset():
    assert keep_session_id_on_reset("cursor")
    assert keep_session_id_on_reset("codex")
    assert keep_session_id_on_reset("antigravity")
    assert keep_session_id_on_reset("grok")
    assert keep_session_id_on_reset("grok_bot")
    assert not keep_session_id_on_reset("claude")


def test_grok_env_exposes_session_and_package(tmp_path, monkeypatch):
    import devscope_bridge.session_store as store

    monkeypatch.setattr(store, "SESSIONS_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(store, "BRIDGE_DIR", tmp_path)
    env = GrokBackend().env("grok-chat", str(tmp_path))
    assert env["DEVSCOPE_SESSION"] == "grok-chat"
    from pathlib import Path
    import devscope_bridge

    root = str(Path(devscope_bridge.__file__).resolve().parent.parent)
    assert root in env.get("PYTHONPATH", "")


def test_grok_resume_and_bot_always_approve():
    backend = GrokBackend()
    try:
        cmd = backend.build_cmd("/bin/grok", "hi", "01abc", "act", "grok-4.6", "/repo")
        assert cmd[0] == "/bin/grok"
        assert "--resume" in cmd and "01abc" in cmd
        assert "--output-format" in cmd and "streaming-messages-json" in cmd
        assert "--include-partial-messages" in cmd
        assert "--prompt-file" in cmd
        assert "-p" not in cmd
        path = cmd[cmd.index("--prompt-file") + 1]
        assert Path(path).read_text(encoding="utf-8") == "hi"
        assert "--always-approve" not in cmd
        assert "--rules" in cmd
        assert "browser-control" in cmd[cmd.index("--rules") + 1]
    finally:
        backend.cleanup_turn()
    bot = GrokBotBackend()
    try:
        cmd = bot.build_cmd("/bin/grok", "hi", None, "act", None, "/repo")
        assert "--always-approve" in cmd
        assert "--prompt-file" in cmd
        assert Path(cmd[cmd.index("--prompt-file") + 1]).read_text(encoding="utf-8") == "hi"
    finally:
        bot.cleanup_turn()


def test_grok_prompt_file_keeps_leading_dashes():
    backend = GrokBackend()
    prompt = "--- PAGE CONTEXT ---\n[BROWSER TAB BOUND] tab_id=12\napply now"
    try:
        cmd = backend.build_cmd("/bin/grok", prompt, None, "act", None, "/tmp")
        assert cmd.count("--prompt-file") == 1
        path = cmd[cmd.index("--prompt-file") + 1]
        assert Path(path).read_text(encoding="utf-8") == prompt
        assert not any(a.startswith("--- PAGE") for a in cmd)
    finally:
        backend.cleanup_turn()
        assert not Path(path).exists()


def test_codex_exec_resume_argv():
    cmd = CodexExecBackend().build_cmd(
        "/bin/codex", "hi", "thr_1", "inspect", "gpt-5.6-sol", "/tmp",
    )
    assert cmd[:4] == ["/bin/codex", "exec", "resume", "thr_1"]
    assert "--json" in cmd
    assert "-m" in cmd
    assert cmd[-1].startswith("You are in Inspect") or cmd[-1] == "hi" or "hi" in cmd[-1]


def test_codex_exec_new_thread_sandbox():
    cmd = CodexExecBackend().build_cmd("/bin/codex", "hi", None, "inspect", None, "/repo")
    assert "-s" in cmd
    assert "read-only" in cmd
    cmd_act = CodexExecBackend().build_cmd("/bin/codex", "hi", None, "act", None, "/repo")
    assert "workspace-write" in cmd_act
