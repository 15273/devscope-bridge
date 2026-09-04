import type { SchedulePlaybook } from './bridge';

export const LINKEDIN_WATCH_TITLE = 'צופה LinkedIn';

export const LINKEDIN_WATCH_INSTRUCTION = `You are the LinkedIn activity watcher for this DevScope schedule. Drive the live Chrome tab with browser-control (snapshot, click, hover) — the dedicated DevScope mouse is visible.

Each run:
1. browser_list_tabs. Prefer an existing linkedin.com tab. If none, browser_new_page the feed URL.
2. browser_navigate to the feed, wait for cards, linkedin_scrape_feed(max_posts=25).
3. browser_navigate to https://www.linkedin.com/notifications/ then linkedin_scrape_notifications.
4. Treat playbook.watch.seen_urns / seen_notification_ids as already handled. Only NEW items.
5. Auto-engage when playbook.watch.allow_auto_engage is true:
   - Like new feed posts matching like_keywords (or all new if like_new) via linkedin_react.
   - Comment on posts matching comment_keywords using comment_style via linkedin_fill_comment(..., allow_send=true).
6. Never InMail strangers, never apply to jobs, never purchase.
7. task_update done with result_summary of new items + actions.
8. schedule_playbook_update watch.seen_* (last 200) so the next run diffs correctly.
If LinkedIn shows a login wall, stop and report that.`;

export function linkedinWatchPlaybook(rules: {
  likeKeywords: string[];
  commentKeywords: string[];
  commentStyle: string;
  likeNew: boolean;
}): SchedulePlaybook {
  return {
    version: 1,
    site: 'linkedin.com',
    entry_urls: [
      'https://www.linkedin.com/feed/',
      'https://www.linkedin.com/notifications/',
    ],
    workflow: [
      'Open or reuse a LinkedIn tab',
      'Scrape feed for new posts',
      'Scrape notifications',
      'Like / comment only on NEW items matching watch rules',
      'Persist seen ids via schedule_playbook_update',
    ],
    selectors: {
      feed_card: 'div.feed-shared-update-v2, div[data-urn*="urn:li:activity"]',
      notification_card: 'article.nt-card, li.notification-card',
    },
    checklist: [
      'DevScope side panel connected',
      'User is logged into LinkedIn in Chrome',
    ],
    notes: 'Scheduled LinkedIn watcher with auto-engage.',
    watch: {
      allow_auto_engage: true,
      like_new: rules.likeNew,
      like_keywords: rules.likeKeywords,
      comment_keywords: rules.commentKeywords,
      comment_style: rules.commentStyle,
      seen_urns: [],
      seen_notification_ids: [],
    },
  };
}
