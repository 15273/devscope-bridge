/**
 * LinkedIn comment helper — opens comment box and fills text; send only when allowSend.
 */

function openCommentBox(postSelector?: string): HTMLElement | null {
  const root = postSelector ? document.querySelector(postSelector) : document;
  if (!root) return null;
  const commentBtn = root.querySelector(
    'button[aria-label*="Comment"], button.social-actions-button--comment',
  ) as HTMLButtonElement | null;
  commentBtn?.click();
  const box =
    root.querySelector('.comments-comment-box__form .ql-editor') ||
    root.querySelector('[data-test-ql-editor-contenteditable="true"]');
  return box as HTMLElement | null;
}

function fillComment(text: string, postSelector?: string): { filled: boolean } {
  const editor = openCommentBox(postSelector) || (document.querySelector('.ql-editor') as HTMLElement | null);
  if (!editor) return { filled: false };
  editor.focus();
  editor.textContent = text;
  editor.dispatchEvent(new InputEvent('input', { bubbles: true }));
  return { filled: true };
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg?.type === 'LINKEDIN_FILL_COMMENT') {
    const text = String(msg.text || '');
    const postSelector = msg.postSelector ? String(msg.postSelector) : undefined;
    const allowSend = Boolean(msg.allowSend);
    const result = fillComment(text, postSelector);
    let sent = false;
    if (result.filled && allowSend) {
      const btn = document.querySelector(
        'button.comments-comment-box__submit-button, button[aria-label*="Post comment"]',
      ) as HTMLButtonElement | null;
      if (btn) {
        btn.click();
        sent = true;
      }
    }
    sendResponse({ success: result.filled, ...result, sent, draft: !sent });
    return true;
  }
  return false;
});

export {};
