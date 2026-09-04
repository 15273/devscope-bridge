/**
 * Dedicated on-page agent mouse: a persistent cursor that moves to each
 * click/fill/hover, plus a ripple on click. Pointer-events none.
 */
const STYLE_ID = 'devscope-agent-indicator-style';
const CURSOR_ID = 'devscope-agent-cursor';
const FADE_MS = 4500;

let fadeTimer: number | null = null;

function ensureStyles(): void {
  if (document.getElementById(STYLE_ID)) return;
  const style = document.createElement('style');
  style.id = STYLE_ID;
  style.textContent = `
    @keyframes ds-agent-pulse {
      0% { transform: translate(-50%, -50%) scale(0.4); opacity: 0.85; }
      100% { transform: translate(-50%, -50%) scale(2.2); opacity: 0; }
    }
    .ds-agent-ripple {
      position: fixed;
      width: 28px;
      height: 28px;
      border-radius: 50%;
      border: 2px solid rgba(232, 109, 19, 0.9);
      background: rgba(232, 109, 19, 0.15);
      pointer-events: none;
      z-index: 2147483646;
      animation: ds-agent-pulse 650ms ease-out forwards;
    }
    #${CURSOR_ID} {
      position: fixed;
      left: 0;
      top: 0;
      width: 22px;
      height: 22px;
      pointer-events: none;
      z-index: 2147483647;
      opacity: 0;
      transition: transform 180ms cubic-bezier(0.22, 1, 0.36, 1), opacity 160ms ease;
      filter: drop-shadow(0 1px 2px rgba(0,0,0,0.35));
    }
    #${CURSOR_ID}.ds-on { opacity: 1; }
    #${CURSOR_ID}.ds-press { transform: translate(var(--ds-x), var(--ds-y)) scale(0.86); }
    #${CURSOR_ID} svg { display: block; }
    #${CURSOR_ID} .ds-label {
      position: absolute;
      left: 16px;
      top: 16px;
      padding: 1px 5px;
      border-radius: 4px;
      background: rgb(232 109 19);
      color: #fff;
      font: 600 9px/14px ui-sans-serif, system-ui, sans-serif;
      white-space: nowrap;
    }
  `;
  document.documentElement.appendChild(style);
}

function cursorEl(): HTMLElement {
  ensureStyles();
  let el = document.getElementById(CURSOR_ID);
  if (el) return el;
  el = document.createElement('div');
  el.id = CURSOR_ID;
  el.innerHTML = `
    <svg width="22" height="22" viewBox="0 0 24 24" aria-hidden="true">
      <path fill="#E86D13" stroke="#fff" stroke-width="1.2"
        d="M4.2 3.2l15.1 8.4-6.6 1.5 2.6 6.4-2.8 1.2-2.6-6.4-5.7 4.1z"/>
    </svg>
    <span class="ds-label">DevScope</span>
  `;
  document.documentElement.appendChild(el);
  return el;
}

function moveCursor(x: number, y: number, press: boolean): void {
  const el = cursorEl();
  el.style.setProperty('--ds-x', `${x}px`);
  el.style.setProperty('--ds-y', `${y}px`);
  el.style.transform = `translate(${x}px, ${y}px)${press ? ' scale(0.86)' : ''}`;
  el.classList.add('ds-on');
  el.classList.toggle('ds-press', press);
  if (fadeTimer != null) window.clearTimeout(fadeTimer);
  fadeTimer = window.setTimeout(() => {
    el.classList.remove('ds-on', 'ds-press');
  }, FADE_MS);
}

function showRipple(x: number, y: number): void {
  ensureStyles();
  const el = document.createElement('div');
  el.className = 'ds-agent-ripple';
  el.style.left = `${x}px`;
  el.style.top = `${y}px`;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 700);
}

function centerOfSelector(selector: string): { x: number; y: number } | null {
  try {
    const node = document.querySelector(selector);
    if (!node) return null;
    const r = node.getBoundingClientRect();
    return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
  } catch {
    return null;
  }
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg?.kind !== 'show_agent_action') return;
  const selector = typeof msg.selector === 'string' ? msg.selector : '';
  const x = typeof msg.x === 'number' ? msg.x : null;
  const y = typeof msg.y === 'number' ? msg.y : null;
  const action = msg.action === 'hover' || msg.action === 'fill' ? msg.action : 'click';
  const point =
    x != null && y != null ? { x, y } : selector ? centerOfSelector(selector) : null;
  if (point) {
    moveCursor(point.x, point.y, action === 'click');
    if (action === 'click') showRipple(point.x, point.y);
  }
  sendResponse({ ok: true });
  return true;
});

export {};
