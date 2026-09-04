"""LinkedIn scheduled-watch instruction + playbook.watch helpers."""

from __future__ import annotations

from typing import Any

WATCH_ENTRY_FEED = "https://www.linkedin.com/feed/"
WATCH_ENTRY_NOTIFICATIONS = "https://www.linkedin.com/notifications/"

WATCH_INSTRUCTION = """\
You are the LinkedIn activity watcher for this DevScope schedule. Drive the live Chrome
tab with browser-control (snapshot, click, hover) — the dedicated DevScope mouse is visible.

Each run:
1. browser_list_tabs. Prefer an existing linkedin.com tab. If none, browser_new_page the feed URL.
2. browser_navigate to the feed, wait for cards, linkedin_scrape_feed(max_posts=25).
3. browser_navigate to https://www.linkedin.com/notifications/ then linkedin_scrape_notifications.
4. Treat playbook.watch.seen_urns / seen_notification_ids as already handled. Only NEW items.
5. Auto-engage when playbook.watch.allow_auto_engage is true (this schedule):
   - Like new feed posts whose author/text matches like_keywords (or all new if like_new is true)
     via linkedin_react(reaction="like", post_selector=…).
   - Comment on posts matching comment_keywords using comment_style via
     linkedin_fill_comment(..., allow_send=true).
6. Never InMail strangers, never apply to jobs, never purchase, never delete.
7. task_update the worker to done with result_summary: new notifications, new posts, likes, comments.
8. schedule_playbook_update({watch:{seen_urns:[…last 200], seen_notification_ids:[…last 200]}})
   and last_success_at so the next run diffs correctly.
If LinkedIn shows a login wall, stop and report that — do not invent activity.
"""


def default_watch(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    watch: dict[str, Any] = {
        "allow_auto_engage": True,
        "like_new": True,
        "like_keywords": [],
        "comment_keywords": [],
        "comment_style": "",
        "seen_urns": [],
        "seen_notification_ids": [],
    }
    if overrides:
        watch.update(overrides)
    return watch


def format_watch_block(watch: object) -> str:
    if not isinstance(watch, dict) or not watch:
        return ""
    lines = ["## LinkedIn watch state"]
    lines.append(f"allow_auto_engage: {bool(watch.get('allow_auto_engage'))}")
    lines.append(f"like_new: {bool(watch.get('like_new'))}")
    likes = watch.get("like_keywords") or []
    comments = watch.get("comment_keywords") or []
    if likes:
        lines.append("like_keywords: " + ", ".join(str(x) for x in likes))
    if comments:
        lines.append("comment_keywords: " + ", ".join(str(x) for x in comments))
    style = str(watch.get("comment_style") or "").strip()
    if style:
        lines.append(f"comment_style: {style}")
    seen = watch.get("seen_urns") or []
    nids = watch.get("seen_notification_ids") or []
    lines.append(f"seen_urns ({len(seen)}): keep these as already handled")
    lines.append(f"seen_notification_ids ({len(nids)}): keep these as already handled")
    return "\n".join(lines)
