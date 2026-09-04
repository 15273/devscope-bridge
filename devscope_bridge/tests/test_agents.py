from devscope_bridge.agents import (
    VALID_AGENTS,
    keep_session_id_on_reset,
    parse_agent,
)
from devscope_bridge.session_manager_codex import CodexExecBackend


def test_parse_agent():
    assert parse_agent("codex") == "codex"
    assert parse_agent("antigravity") == "antigravity"
    assert parse_agent("nope") == "claude"
    assert VALID_AGENTS == {"claude", "cursor", "codex", "antigravity"}


def test_keep_id_on_reset():
    assert keep_session_id_on_reset("cursor")
    assert keep_session_id_on_reset("codex")
    assert keep_session_id_on_reset("antigravity")
    assert not keep_session_id_on_reset("claude")


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
