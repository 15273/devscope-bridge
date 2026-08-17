/**
 * LinkedIn feed scraper for DevScope — collects visible feed cards.
 * Guarded mode: read-only; no clicks on Post/Comment/Send.
 */

function textOf(el: Element | null | undefined): string {
  return (el?.textContent || '').replace(/\s+/g, ' ').trim();
}

function scrapeFeedCards(maxPosts = 20): Array<Record<string, string>> {
  const cards = Array.from(
    document.querySelectorAll(
      'div.feed-shared-update-v2, div[data-urn*="urn:li:activity"], article.main-feed-activity',
    ),
  ).slice(0, maxPosts);

  return cards.map((card) => {
    const urn = card.getAttribute('data-urn') || card.getAttribute('data-id') || '';
    const authorEl =
      card.querySelector('.update-components-actor__name') ||
      card.querySelector('.feed-shared-actor__name') ||
      card.querySelector('span[dir="ltr"] span');
    const textEl =
      card.querySelector('.feed-shared-update-v2__description') ||
      card.querySelector('.feed-shared-text') ||
      card.querySelector('[data-test-id="main-feed-activity-card__commentary"]');
    const linkEl = card.querySelector('a[href*="/feed/update/"]') as HTMLAnchorElement | null;
    return {
      urn,
      author: textOf(authorEl),
      text: textOf(textEl),
      postUrl: linkEl?.href || window.location.href,
    };
  });
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg?.type === 'LINKEDIN_SCRAPE_FEED') {
    const maxPosts = Number(msg.maxPosts) || 20;
    sendResponse({ success: true, posts: scrapeFeedCards(maxPosts) });
    return true;
  }
  return false;
});

export {};
