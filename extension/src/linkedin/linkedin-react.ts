/**
 * LinkedIn reactions (Like) on a visible feed card.
 */

function findCard(postSelector?: string): Element | null {
  if (postSelector) {
    try {
      return document.querySelector(postSelector);
    } catch {
      return null;
    }
  }
  return (
    document.querySelector('div.feed-shared-update-v2') ||
    document.querySelector('div[data-urn*="urn:li:activity"]')
  );
}

function likeButton(root: Element): HTMLButtonElement | null {
  const liked = root.querySelector(
    'button[aria-pressed="true"][aria-label*="Like"], button.react-button--active',
  ) as HTMLButtonElement | null;
  if (liked) return liked;
  return root.querySelector(
    [
      'button[aria-label*="Like"]',
      'button.react-button__trigger',
      'button.social-actions-button--react',
    ].join(', '),
  ) as HTMLButtonElement | null;
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg?.type !== 'LINKEDIN_REACT') return false;
  const reaction = String(msg.reaction || 'like');
  if (reaction !== 'like') {
    sendResponse({ success: false, error: `unsupported reaction: ${reaction}` });
    return true;
  }
  const card = findCard(msg.postSelector ? String(msg.postSelector) : undefined);
  if (!card) {
    sendResponse({ success: false, error: 'post card not found' });
    return true;
  }
  const btn = likeButton(card);
  if (!btn) {
    sendResponse({ success: false, error: 'like button not found' });
    return true;
  }
  const already = btn.getAttribute('aria-pressed') === 'true' || btn.classList.contains('react-button--active');
  if (!already) btn.click();
  sendResponse({ success: true, liked: true, already });
  return true;
});

export {};
