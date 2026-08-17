/**
 * agent_visual_indicator.ts — on-page click/fill ripple (Claude parity).
 */
const STYLE_ID = 'devscope-agent-indicator-style';

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
      border: 2px solid rgba(59, 130, 246, 0.9);
      background: rgba(59, 130, 246, 0.15);
      pointer-events: none;
      z-index: 2147483646;
      animation: ds-agent-pulse 650ms ease-out forwards;
    }
  `;
  document.documentElement.appendChild(style);
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
  if (x != null && y != null) {
    showRipple(x, y);
  } else if (selector) {
    const c = centerOfSelector(selector);
    if (c) showRipple(c.x, c.y);
  }
  sendResponse({ ok: true });
  return true;
});

export {};
