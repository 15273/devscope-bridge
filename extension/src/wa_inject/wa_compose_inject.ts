/**
 * wa_compose_inject.ts — DevScope in-page assistant for WhatsApp Web.
 *
 * Adds a floating "✨ נסח" button whenever the compose box is visible.
 * On click: asks the bridge cockpit assistant (via service worker) for a
 * reply suggestion and pre-fills the compose box — the user sends with
 * WhatsApp's own send button. Zero autonomous sends.
 *
 * Runs in ISOLATED world — no window.require() access. Store + bridge
 * calls go through the service_worker.ts message handler.
 */

const BTN_ID = 'ds-wa-draft-btn';
const COMPOSER_SEL = "footer [contenteditable='true'][role='textbox']";

function getComposer(): HTMLElement | null {
  return document.querySelector(COMPOSER_SEL);
}

function mountButton(): void {
  if (document.getElementById(BTN_ID)) return;
  const btn = document.createElement('button');
  btn.id = BTN_ID;
  btn.type = 'button';
  btn.textContent = '✨ נסח';
  btn.title = 'הצעת ניסוח (DevScope)';
  btn.setAttribute('dir', 'rtl');
  btn.style.cssText = [
    'position:fixed',
    'bottom:90px',
    'right:14px',
    'background:linear-gradient(135deg,#1a1a2e 0%,#16213e 100%)',
    'color:#f0c040',
    'border:1px solid rgba(240,192,64,0.35)',
    'border-radius:20px',
    'padding:5px 13px',
    'font-size:12.5px',
    'font-weight:600',
    'cursor:pointer',
    'z-index:9999',
    'font-family:system-ui,sans-serif',
    'direction:rtl',
    'box-shadow:0 2px 10px rgba(0,0,0,0.5)',
    'transition:opacity 0.2s,transform 0.15s',
    'line-height:1.5',
    'white-space:nowrap',
    'user-select:none',
  ].join(';');
  btn.addEventListener('mouseenter', () => {
    btn.style.transform = 'scale(1.06)';
    btn.style.boxShadow = '0 3px 14px rgba(0,0,0,0.6)';
  });
  btn.addEventListener('mouseleave', () => {
    btn.style.transform = 'scale(1)';
    btn.style.boxShadow = '0 2px 10px rgba(0,0,0,0.5)';
  });
  btn.addEventListener('click', onDraftClick);
  document.body.appendChild(btn);
}

function removeButton(): void {
  document.getElementById(BTN_ID)?.remove();
}

let _syncTimer: ReturnType<typeof setTimeout> | null = null;

function syncButton(): void {
  if (_syncTimer) clearTimeout(_syncTimer);
  _syncTimer = setTimeout(() => {
    if (getComposer()) mountButton();
    else removeButton();
  }, 150);
}

async function onDraftClick(): Promise<void> {
  const btn = document.getElementById(BTN_ID) as HTMLButtonElement | null;
  if (!btn || btn.disabled) return;
  btn.disabled = true;
  btn.textContent = '⏳ מייצר...';
  btn.style.opacity = '0.72';

  try {
    const resp = await chrome.runtime.sendMessage({ kind: 'wa_draft_request' }) as
      | { ok: true; suggestion: string }
      | { ok: false; error: string };

    if (resp?.ok && resp.suggestion) {
      fillComposer(resp.suggestion);
      btn.textContent = '✅ נוסח!';
      setTimeout(resetBtn, 2200);
    } else {
      const msg = (resp as { error?: string })?.error ?? 'שגיאה';
      btn.textContent = '❌ ' + msg.slice(0, 18);
      setTimeout(resetBtn, 3500);
    }
  } catch {
    btn.textContent = '❌ שגיאה';
    setTimeout(resetBtn, 3000);
  }

  function resetBtn() {
    if (!btn) return;
    btn.textContent = '✨ נסח';
    btn.disabled = false;
    btn.style.opacity = '1';
  }
}

function fillComposer(text: string): void {
  const el = getComposer();
  if (!el) return;
  el.focus();
  // execCommand is the most reliable way to fill WhatsApp's React-managed
  // contenteditable — it fires native Input events that React picks up.
  document.execCommand('selectAll', false);
  document.execCommand('insertText', false, text);
}

// Show / hide button as chat compose box appears / disappears.
const _observer = new MutationObserver(syncButton);
_observer.observe(document.body, { childList: true, subtree: true });
syncButton();
