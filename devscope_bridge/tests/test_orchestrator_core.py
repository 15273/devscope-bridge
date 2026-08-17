# devscope_bridge/tests/test_orchestrator_core.py
from devscope_bridge import agent_policies as ap


def test_worker_policy_lists_sensitive_actions():
    policy = ap.WORKER_SAFETY_POLICY
    for word in ("send", "purchase", "delete", "money", "task_request_approval"):
        assert word in policy.lower() or word in policy


def test_build_mom_prompt_includes_board_digest():
    prompt = ap.build_mom_prompt(digest="3 new tasks: A, B, C")
    assert "3 new tasks" in prompt
    assert "domain" in prompt.lower()


def test_build_domain_prompt_names_domain_and_workers():
    prompt = ap.build_domain_prompt(domain="browser", digest="task X assigned")
    assert "browser" in prompt
    assert "worker_unit" in prompt


def test_build_worker_prompt_includes_instruction_and_policy():
    prompt = ap.build_worker_prompt(task_id="abc123", title="Check site",
                                    instruction="open example.com and read H1")
    assert "abc123" in prompt
    assert "open example.com" in prompt
    assert "task_request_approval" in prompt


# ── Task 2: pure decision core ────────────────────────────────────────────────

import pytest
from devscope_bridge import task_store, orchestrator_core as oc


@pytest.fixture
def store(tmp_path):
    task_store.set_db_path(tmp_path / "agent_tasks.db")
    task_store.init_db()
    yield task_store
    task_store.set_db_path(None)


def test_collect_buckets_new_and_ready_and_approvals(store):
    new = store.create_task(title="N", kind="mom_task", status="new")
    rdy = store.create_task(title="R", kind="worker_unit", domain="browser", status="ready")
    gate = store.create_task(title="G", kind="worker_unit", status="awaiting_approval")
    store.request_approval(gate, action="send")
    b = oc.collect()
    assert new in [t["id"] for t in b.new_tasks]
    assert rdy in [t["id"] for t in b.ready_workers]
    assert any(a["task_id"] == gate for a in b.pending_approvals)


def test_should_wake_mom_only_when_new_or_assigned_present(store):
    assert oc.should_wake_mom(oc.collect()) is False
    store.create_task(title="N", kind="mom_task", status="new")
    assert oc.should_wake_mom(oc.collect()) is True


def test_domains_needing_triage_lists_only_domains_with_assigned(store):
    store.create_task(title="A", kind="mom_task", domain="browser", status="assigned")
    store.create_task(title="B", kind="mom_task", domain="research", status="new")
    doms = oc.domains_needing_triage(oc.collect(), ("browser", "research", "dev"))
    assert doms == ["browser"]


def test_select_ready_workers_respects_capacity(store):
    for i in range(5):
        store.create_task(title=f"W{i}", kind="worker_unit", status="ready")
    b = oc.collect()
    picked = oc.select_ready_workers(b, running_count=2, max_workers=4)
    assert len(picked) == 2  # 4 cap - 2 running


def test_select_ready_workers_orders_by_parent_priority(store):
    """A high-priority parent's worker_unit must dispatch before a low-priority
    parent's, even though worker_units are all created at priority 0 themselves
    and the low one was created first (so plain FIFO would pick it)."""
    lo = store.create_task(title="LoP", kind="mom_task", status="in_progress", priority=1)
    hi = store.create_task(title="HiP", kind="mom_task", status="in_progress", priority=8)
    store.create_task(title="loW", kind="worker_unit", parent_id=lo, status="ready")
    store.create_task(title="hiW", kind="worker_unit", parent_id=hi, status="ready")
    b = oc.collect()
    picked = oc.select_ready_workers(b, running_count=3, max_workers=4)  # capacity 1
    assert len(picked) == 1
    assert picked[0]["parent_id"] == hi  # enrichment (priority 8) wins the slot


def test_running_worker_count_ignores_parent_tasks(store):
    """Worker capacity must reflect in-progress WORKER_UNITS only. In-progress
    mom/domain parent tasks must NOT consume worker slots (else a few stuck
    parents deadlock all dispatch — capacity 0)."""
    store.create_task(title="W", kind="worker_unit", status="in_progress")
    store.create_task(title="P", kind="mom_task", status="in_progress")
    store.create_task(title="D", kind="domain_task", status="in_progress")
    b = oc.collect()
    assert oc.running_worker_count(b) == 1


def test_running_worker_count_zero_when_only_parents_stuck(store):
    store.create_task(title="P1", kind="mom_task", status="in_progress")
    store.create_task(title="P2", kind="domain_task", status="in_progress")
    b = oc.collect()
    assert oc.running_worker_count(b) == 0  # parents don't block dispatch


def test_materialise_due_schedules_creates_tasks_and_advances(store):
    sid = store.add_schedule(title="ping",
        template={"title": "Ping", "kind": "mom_task", "recurrence": {"every_minutes": 60}},
        next_run_at="2000-01-01 00:00:00")
    created = oc.materialise_due_schedules(now="2026-06-08 12:00:00")
    assert created == 1
    assert any(t["title"] == "Ping" for t in store.list_tasks(status="new"))
    # next_run advanced into the future
    assert store.due_schedules(now="2026-06-08 12:00:00") == []


def test_materialise_injects_playbook_into_instruction(store):
    store.add_schedule(
        title="LI",
        template={
            "title": "LinkedIn",
            "kind": "mom_task",
            "instruction": "Post update",
            "recurrence": {"every_minutes": 60},
        },
        playbook={"site": "linkedin.com", "selectors": {"composer": ".ql-editor"}},
        next_run_at="2000-01-01 00:00:00",
    )
    oc.materialise_due_schedules(now="2026-06-08 12:00:00")
    task = store.list_tasks(status="new")[0]
    assert "linkedin.com" in task["instruction"]
    assert ".ql-editor" in task["instruction"]
    assert task["schedule_id"] is not None


def test_build_worker_prompt_mentions_schedule_playbook_update():
    prompt = ap.build_worker_prompt(
        task_id="w1", title="Post", instruction="Go",
        schedule_id=42,
    )
    assert "schedule #42" in prompt
    assert "schedule_playbook_update" in prompt


def test_next_run_at_every_minutes_and_daily():
    assert oc._next_run_at({"every_minutes": 30}, "2026-06-08 12:00:00") == "2026-06-08 12:30:00"
    assert oc._next_run_at({"daily_at": "08:00"}, "2026-06-08 12:00:00") == "2026-06-09 08:00:00"


# ── parent roll-up (close in_progress parent once its worker_units finish) ─────

def test_parent_ready_for_rollup_when_all_units_terminal(store):
    parent = store.create_task(title="P", kind="mom_task", domain="browser", status="in_progress")
    store.create_task(title="u1", kind="worker_unit", parent_id=parent, domain="browser", status="done")
    ready = oc.parents_ready_for_rollup(oc.collect(), ("browser", "research", "dev"))
    assert parent in [t["id"] for t in ready]


def test_parent_not_ready_while_a_unit_still_running(store):
    parent = store.create_task(title="P", kind="mom_task", domain="browser", status="in_progress")
    store.create_task(title="u1", kind="worker_unit", parent_id=parent, domain="browser", status="done")
    store.create_task(title="u2", kind="worker_unit", parent_id=parent, domain="browser", status="in_progress")
    ready = oc.parents_ready_for_rollup(oc.collect(), ("browser",))
    assert parent not in [t["id"] for t in ready]


def test_parent_without_units_is_not_a_rollup_candidate(store):
    # a childless in_progress task (e.g. a leaf worker_unit) must not roll itself up
    leaf = store.create_task(title="leaf", kind="worker_unit", domain="browser", status="in_progress")
    ready = oc.parents_ready_for_rollup(oc.collect(), ("browser",))
    assert leaf not in [t["id"] for t in ready]


def test_parent_rollup_respects_domain_filter(store):
    parent = store.create_task(title="P", kind="mom_task", domain="research", status="in_progress")
    store.create_task(title="u1", kind="worker_unit", parent_id=parent, domain="research", status="done")
    ready = oc.parents_ready_for_rollup(oc.collect(), ("browser", "dev"))
    assert parent not in [t["id"] for t in ready]


def test_build_domain_prompt_includes_rollup_section():
    prompt = ap.build_domain_prompt(domain="browser", digest="(none)",
                                    rollup_digest="- [p1] done: H1 = Example Domain")
    assert "H1 = Example Domain" in prompt
    assert "done" in prompt.lower()
