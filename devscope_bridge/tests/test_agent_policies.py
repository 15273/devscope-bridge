from devscope_bridge import agent_policies as ap


def test_guarded_worker_prompt_uses_full_safety_policy():
    p = ap.build_worker_prompt("t1", "Title", "do the thing")  # default guarded
    assert ap.WORKER_SAFETY_POLICY in p
    assert ap.WORKER_SAFETY_POLICY_E2E not in p


def test_e2e_worker_prompt_uses_e2e_policy():
    p = ap.build_worker_prompt("t1", "Title", "do the thing", autonomy="e2e")
    assert ap.WORKER_SAFETY_POLICY_E2E in p
    assert ap.WORKER_SAFETY_POLICY not in p


def test_e2e_policy_still_gates_money_and_purchase():
    txt = ap.WORKER_SAFETY_POLICY_E2E
    assert "purchase" in txt and "money" in txt
    assert "task_request_approval" in txt


def test_worker_prompt_includes_task_id_and_instruction():
    p = ap.build_worker_prompt("abc123", "MyTitle", "step one", autonomy="e2e")
    assert "abc123" in p and "step one" in p and "MyTitle" in p
