/**
 * LinkedIn notifications scraper — visible cards on /notifications/.
 */

function textOf(el: Element | null | undefined): string {
  return (el?.textContent || '').replace(/\s+/g, ' ').trim();
}

export function scrapeNotificationCards(maxItems = 30): Array<Record<string, string>> {
  const cards = Array.from(
    document.querySelectorAll(
      [
        'article.nt-card',
        'div.nt-card',
        'li.notification-card',
        'div[data-finite-scroll-hotkey-item]',
        'section.nt-card',
      ].join(', '),
    ),
  ).slice(0, maxItems);

  return cards.map((card) => {
    const id =
      card.getAttribute('data-id') ||
      card.getAttribute('data-urn') ||
      card.getAttribute('id') ||
      '';
    const link = card.querySelector('a[href]') as HTMLAnchorElement | null;
    const actor =
      card.querySelector('.nt-card__headline') ||
      card.querySelector('.notification-card__title') ||
      card.querySelector('strong') ||
      card.querySelector('span[dir="ltr"]');
    const body =
      card.querySelector('.nt-card__text') ||
      card.querySelector('.notification-card__message') ||
      card.querySelector('p');
    const time =
      card.querySelector('time') ||
      card.querySelector('.nt-card__time-ago') ||
      card.querySelector('span.visually-hidden');
    return {
      id,
      actor: textOf(actor),
      text: textOf(body) || textOf(card).slice(0, 240),
      href: link?.href || '',
      time: textOf(time),
    };
  }).filter((row) => row.text || row.actor);
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg?.type === 'LINKEDIN_SCRAPE_NOTIFICATIONS') {
    const maxItems = Number(msg.maxItems) || 30;
    sendResponse({ success: true, notifications: scrapeNotificationCards(maxItems) });
    return true;
  }
  return false;
});
