# devscope_bridge/tests/test_schedule_playbook.py
from devscope_bridge.schedule_playbook import (
    build_scheduled_instruction,
    format_playbook_block,
    merge_playbook,
    parse_playbook,
)


def test_empty_playbook_injects_nothing():
    assert format_playbook_block({}) == ""
    assert build_scheduled_instruction("Do thing", {}) == "Do thing"


def test_format_playbook_includes_selectors_and_workflow():
    pb = {
        "site": "linkedin.com",
        "entry_urls": ["https://linkedin.com/feed/"],
        "workflow": ["Open composer", "Paste text"],
        "selectors": {"composer": ".ql-editor"},
        "notes": "Wait for modal",
    }
    block = format_playbook_block(pb)
    assert "linkedin.com" in block
    assert ".ql-editor" in block
    assert "Open composer" in block
    assert "Playbook" in block


def test_merge_playbook_extends_lists_and_selectors():
    base = parse_playbook({"selectors": {"a": "1"}, "workflow": ["step1"]})
    merged = merge_playbook(base, {"selectors": {"b": "2"}, "workflow": ["step2"]})
    assert merged["selectors"] == {"a": "1", "b": "2"}
    assert merged["workflow"] == ["step1", "step2"]
    assert merged["learned_from_runs"] == 1


def test_build_scheduled_instruction_appends_playbook():
    text = build_scheduled_instruction(
        "Post update",
        {"workflow": ["Click publish"], "site": "linkedin.com"},
    )
    assert text.startswith("Post update")
    assert "Click publish" in text
