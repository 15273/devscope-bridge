/**
 * LinkedIn composer helper — fills .ql-editor draft without clicking Post.
 */

function findComposer(): HTMLElement | null {
  return (
    document.querySelector('.ql-editor[contenteditable="true"]') ||
    document.querySelector('[data-test-ql-editor-contenteditable="true"]') ||
    document.querySelector('div[role="textbox"][contenteditable="true"]')
  );
}

function isEasyApplyPage(): boolean {
  return Boolean(
    document.querySelector('.jobs-apply-button--top-card') ||
      document.querySelector('button[aria-label*="Easy Apply"]'),
  );
}

function fillComposer(text: string): { filled: boolean; easyApply: boolean; selector: string | null } {
  const easyApply = isEasyApplyPage();
  const editor = findComposer();
  if (!editor) {
    return { filled: false, easyApply, selector: null };
  }
  editor.focus();
  editor.textContent = text;
  editor.dispatchEvent(new InputEvent('input', { bubbles: true }));
  return { filled: true, easyApply, selector: '.ql-editor' };
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg?.type === 'LINKEDIN_FILL_COMPOSER') {
    const text = String(msg.text || '');
    const autoSend = Boolean(msg.autoSend);
    const allowSend = Boolean(msg.allowSend);
    const result = fillComposer(text);
    if (autoSend && allowSend) {
      const postBtn = document.querySelector(
        'button.share-actions__primary-action, button[aria-label*="Post"]',
      ) as HTMLButtonElement | null;
      if (postBtn) postBtn.click();
      sendResponse({ success: true, ...result, sent: true });
    } else {
      sendResponse({ success: result.filled, ...result, sent: false, draft: true });
    }
    return true;
  }
  return false;
});

export {};
