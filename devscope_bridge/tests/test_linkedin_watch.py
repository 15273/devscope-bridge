from devscope_bridge.linkedin_watch import (
    WATCH_INSTRUCTION,
    default_watch,
    format_watch_block,
)


def test_watch_instruction_covers_browser_and_diff():
    text = WATCH_INSTRUCTION
    assert "linkedin_scrape_feed" in text
    assert "linkedin_scrape_notifications" in text
    assert "linkedin_react" in text
    assert "linkedin_fill_comment" in text
    assert "schedule_playbook_update" in text
    assert "login wall" in text.lower()
    assert "InMail" in text


def test_default_watch_and_overrides():
    watch = default_watch({"like_keywords": ["ai"], "like_new": False})
    assert watch["allow_auto_engage"] is True
    assert watch["like_new"] is False
    assert watch["like_keywords"] == ["ai"]
    assert watch["seen_urns"] == []
    assert watch["seen_notification_ids"] == []


def test_format_watch_block_empty():
    assert format_watch_block(None) == ""
    assert format_watch_block({}) == ""
    assert format_watch_block("nope") == ""


def test_format_watch_block_rules_and_seen_counts():
    block = format_watch_block({
        "allow_auto_engage": True,
        "like_new": True,
        "like_keywords": ["hiring", "launch"],
        "comment_keywords": ["open to work"],
        "comment_style": "short professional",
        "seen_urns": ["u1", "u2"],
        "seen_notification_ids": ["n1"],
    })
    assert "allow_auto_engage: True" in block
    assert "like_new: True" in block
    assert "hiring, launch" in block
    assert "open to work" in block
    assert "comment_style: short professional" in block
    assert "seen_urns (2)" in block
    assert "seen_notification_ids (1)" in block
