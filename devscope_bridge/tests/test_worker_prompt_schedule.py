# devscope_bridge/tests/test_worker_prompt_schedule.py
from devscope_bridge.agent_policies import build_worker_prompt


def test_schedule_prompt_includes_report_contract_policy_and_memory():
    prompt = build_worker_prompt(
        "t1", "x", "inst",
        schedule_id=5,
        memory="- slow site",
        autonomy_policy="never post",
        reports_dir="/home/u/.dev-bridge/task_homes/5/reports",
    )
    assert "schedule_run_report" in prompt
    assert "never post" in prompt
    assert "slow site" in prompt
    assert "task_ask_user" in prompt
    assert "/home/u/.dev-bridge/task_homes/5/reports" in prompt


def test_plain_worker_prompt_has_no_schedule_extras():
    prompt = build_worker_prompt("t1", "x", "inst")
    assert "schedule_run_report" not in prompt
    assert "Autonomy policy" not in prompt
    assert "Task memory" not in prompt
