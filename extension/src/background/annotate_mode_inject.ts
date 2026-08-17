/**
 * annotate_mode_inject.ts — in-page multi-element annotate session.
 *
 * Click element → note field appears below it on the page → "Attach to message".
 * Stays active until Esc or stop_annotate_mode. Self-contained for executeScript.
 */

/** Installed in each frame; long-lived until cleanup. */
export function annotateModeInjected(): void {
  const NS = 'data-devscope-annotate';
  const PREV = 'data-ds-prev-outline';
  const SIGNAL = '#E86D13';
  const w = window as unknown as {
    __dsAnnotateCleanup?: () => void;
    __dsAnnotateActive?: boolean;
  };

  if (w.__dsAnnotateActive && typeof w.__dsAnnotateCleanup === 'function') {
    try {
      w.__dsAnnotateCleanup();
    } catch {
      /* re-install after partial teardown */
    }
  }
  w.__dsAnnotateActive = true;

  let activePanel: HTMLElement | null = null;
  let activeTarget: HTMLElement | null = null;
  let pickingEnabled = true;
  let scrollHandler: (() => void) | null = null;

  const restoreOutline = (el: HTMLElement): void => {
    el.style.outline = el.getAttribute(PREV) ?? '';
    el.removeAttribute(PREV);
  };

  const buildSelector = (el: Element): string => {
    if (el.id) return `#${CSS.escape(el.id)}`;
    const parts: string[] = [];
    let cur: Element | null = el;
    while (cur && cur !== document.body && cur !== document.documentElement) {
      const tag = cur.tagName.toLowerCase();
      const parent: Element | null = cur.parentElement;
      if (!parent) {
        parts.unshift(tag);
        break;
      }
      const siblings = Array.from(parent.children).filter((c) => c.tagName === cur!.tagName);
      parts.unshift(siblings.length === 1 ? tag : `${tag}:nth-of-type(${siblings.indexOf(cur) + 1})`);
      if (document.querySelectorAll(parts.join(' > ')).length === 1) break;
      cur = parent;
    }
    return parts.length ? parts.join(' > ') : el.tagName.toLowerCase();
  };

  const computeAriaName = (el: HTMLElement): string | null => {
    const label = el.getAttribute('aria-label');
    if (label) return label;
    const labelledBy = el.getAttribute('aria-labelledby');
    if (labelledBy) {
      const ref = document.getElementById(labelledBy);
      if (ref) return (ref.textContent ?? '').trim() || null;
    }
    const alt = el.getAttribute('alt');
    if (alt) return alt;
    const title = el.getAttribute('title');
    if (title) return title;
    const text = (el.textContent ?? '').trim();
    return text ? text.slice(0, 120) : null;
  };

  const isAnnotateUi = (el: EventTarget | null): boolean => {
    if (!(el instanceof HTMLElement)) return false;
    return Boolean(el.closest(`[${NS}]`));
  };

  const removePanel = (): void => {
    if (scrollHandler) {
      window.removeEventListener('scroll', scrollHandler, true);
      scrollHandler = null;
    }
    activePanel?.remove();
    activePanel = null;
    if (activeTarget) {
      restoreOutline(activeTarget);
      activeTarget = null;
    }
    pickingEnabled = true;
  };

  const positionPanel = (panel: HTMLElement, target: HTMLElement): void => {
    const rect = target.getBoundingClientRect();
    const width = Math.min(Math.max(rect.width, 260), 360);
    let left = rect.left;
    let top = rect.bottom + 8;
    if (left + width > window.innerWidth - 8) {
      left = Math.max(8, window.innerWidth - width - 8);
    }
    if (top + 120 > window.innerHeight) {
      top = Math.max(8, rect.top - 120);
    }
    Object.assign(panel.style, {
      position: 'fixed',
      top: `${top}px`,
      left: `${left}px`,
      width: `${width}px`,
      zIndex: '2147483646',
    });
  };

  const collectElementInfo = (t: HTMLElement, note: string): Record<string, unknown> => {
    const rect = t.getBoundingClientRect();
    const style = window.getComputedStyle(t);
    const inViewport =
      rect.top >= 0 &&
      rect.left >= 0 &&
      rect.bottom <= window.innerHeight &&
      rect.right <= window.innerWidth;
    const chain: string[] = [];
    let node: Element | null = t;
    while (node && node !== document.body && node !== document.documentElement && chain.length < 6) {
      const tag = node.tagName.toLowerCase();
      const id = node.id ? `#${node.id}` : '';
      const cls = Array.from(node.classList)
        .slice(0, 3)
        .map((c) => `.${c}`)
        .join('');
      chain.unshift(`${tag}${id}${cls}`);
      node = node.parentElement;
    }
    let editRef = t.getAttribute('data-edit-ref');
    if (!editRef) {
      editRef = `ref-${Date.now().toString(36)}-${Math.floor(Math.random() * 1e4)}`;
      t.setAttribute('data-edit-ref', editRef);
    }
    return {
      selector: buildSelector(t),
      tag: t.tagName.toLowerCase(),
      text: (t.textContent ?? '').trim().slice(0, 200),
      ariaRole: t.getAttribute('role'),
      ariaName: computeAriaName(t),
      href: t.getAttribute('href'),
      outerHTML: (t.outerHTML ?? '').slice(0, 500),
      boundingBox: {
        x: Math.round(rect.x),
        y: Math.round(rect.y),
        width: Math.round(rect.width),
        height: Math.round(rect.height),
      },
      inViewport,
      cssSnapshot: {
        color: style.color,
        backgroundColor: style.backgroundColor,
        fontSize: style.fontSize,
        fontWeight: style.fontWeight,
        display: style.display,
        position: style.position,
      },
      domChain: chain,
      editRef,
      frameUrl: location.href,
      note: note.trim(),
    };
  };

  const openPanel = (target: HTMLElement): void => {
    removePanel();
    pickingEnabled = false;
    activeTarget = target;
    if (!target.hasAttribute(PREV)) target.setAttribute(PREV, target.style.outline);
    target.style.outline = `2px solid ${SIGNAL}`;

    const panel = document.createElement('div');
    panel.setAttribute(NS, 'panel');
    Object.assign(panel.style, {
      background: '#1a1a1a',
      border: `1px solid ${SIGNAL}`,
      borderRadius: '8px',
      boxShadow: '0 8px 24px rgba(0,0,0,0.35)',
      padding: '10px',
      fontFamily: 'system-ui, sans-serif',
      color: '#f5f5f5',
    } as Partial<CSSStyleDeclaration>);

    const label = document.createElement('div');
    label.setAttribute(NS, '1');
    label.textContent = `<${target.tagName.toLowerCase()}> — what to change here?`;
    Object.assign(label.style, {
      fontSize: '11px',
      fontWeight: '600',
      marginBottom: '6px',
      color: SIGNAL,
    } as Partial<CSSStyleDeclaration>);

    const textarea = document.createElement('textarea');
    textarea.setAttribute(NS, '1');
    textarea.dir = 'auto';
    textarea.placeholder = 'Describe the change…';
    textarea.rows = 2;
    Object.assign(textarea.style, {
      width: '100%',
      boxSizing: 'border-box',
      resize: 'vertical',
      minHeight: '48px',
      maxHeight: '120px',
      padding: '6px 8px',
      fontSize: '13px',
      borderRadius: '4px',
      border: '1px solid #444',
      background: '#111',
      color: '#f5f5f5',
      outline: 'none',
    } as Partial<CSSStyleDeclaration>);

    const row = document.createElement('div');
    row.setAttribute(NS, '1');
    Object.assign(row.style, {
      display: 'flex',
      gap: '6px',
      marginTop: '8px',
      justifyContent: 'flex-end',
    } as Partial<CSSStyleDeclaration>);

    const cancelBtn = document.createElement('button');
    cancelBtn.type = 'button';
    cancelBtn.setAttribute(NS, '1');
    cancelBtn.textContent = 'Cancel';
    Object.assign(cancelBtn.style, {
      padding: '5px 10px',
      fontSize: '12px',
      borderRadius: '4px',
      border: '1px solid #555',
      background: 'transparent',
      color: '#ccc',
      cursor: 'pointer',
    } as Partial<CSSStyleDeclaration>);

    const attachBtn = document.createElement('button');
    attachBtn.type = 'button';
    attachBtn.setAttribute(NS, '1');
    attachBtn.textContent = 'Attach to message';
    Object.assign(attachBtn.style, {
      padding: '5px 12px',
      fontSize: '12px',
      fontWeight: '600',
      borderRadius: '4px',
      border: 'none',
      background: SIGNAL,
      color: '#fff',
      cursor: 'pointer',
    } as Partial<CSSStyleDeclaration>);

    cancelBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      removePanel();
    });

    attachBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      const info = collectElementInfo(target, textarea.value);
      chrome.runtime.sendMessage({ kind: 'annotation_attached', element: info }).catch(() => {});
      target.style.outline = `2px dashed ${SIGNAL}`;
      target.removeAttribute(PREV);
      activePanel?.remove();
      activePanel = null;
      activeTarget = null;
      pickingEnabled = true;
    });

    row.append(cancelBtn, attachBtn);
    panel.append(label, textarea, row);
    document.documentElement.appendChild(panel);
    activePanel = panel;
    positionPanel(panel, target);

    scrollHandler = (): void => {
      if (activePanel && activeTarget) positionPanel(activePanel, activeTarget);
    };
    window.addEventListener('scroll', scrollHandler, true);

    setTimeout(() => textarea.focus(), 0);
  };

  const banner = document.createElement('div');
  banner.setAttribute(NS, '1');
  Object.assign(banner.style, {
    position: 'fixed',
    top: '0',
    left: '0',
    right: '0',
    zIndex: '2147483647',
    background: SIGNAL,
    color: '#fff',
    font: '600 13px system-ui, sans-serif',
    textAlign: 'center',
    padding: '8px',
    pointerEvents: 'none',
  } as Partial<CSSStyleDeclaration>);
  banner.textContent =
    'DevScope · click an element · write a note below it · Attach to message · Esc when done';
  document.documentElement.appendChild(banner);
  document.body.style.cursor = 'crosshair';

  const cleanup = (): void => {
    removePanel();
    document.querySelectorAll(`[${NS}]`).forEach((e) => e.remove());
    document.removeEventListener('mousemove', onMove, true);
    document.removeEventListener('click', onClick, true);
    document.removeEventListener('keydown', onKey, true);
    document.querySelectorAll<HTMLElement>(`[${PREV}]`).forEach(restoreOutline);
    document.body.style.cursor = '';
    w.__dsAnnotateCleanup = undefined;
    w.__dsAnnotateActive = false;
    chrome.runtime.sendMessage({ kind: 'annotate_mode_ended' }).catch(() => {});
  };
  w.__dsAnnotateCleanup = cleanup;

  function onMove(e: MouseEvent): void {
    if (!pickingEnabled || activePanel) return;
    const t = e.target as HTMLElement;
    if (!t || isAnnotateUi(t)) return;
    document.querySelectorAll<HTMLElement>(`[${PREV}]`).forEach((el) => {
      if (el !== t && el !== activeTarget) restoreOutline(el);
    });
    if (!t.hasAttribute(PREV) && t !== activeTarget) {
      t.setAttribute(PREV, t.style.outline);
      t.style.outline = `2px solid ${SIGNAL}`;
    }
  }

  function onClick(e: MouseEvent): void {
    if (isAnnotateUi(e.target)) return;
    if (!pickingEnabled || activePanel) return;
    const t = e.target as HTMLElement;
    if (!t) return;
    e.preventDefault();
    e.stopPropagation();
    openPanel(t);
  }

  function onKey(e: KeyboardEvent): void {
    if (e.key === 'Escape') {
      if (activePanel) {
        removePanel();
        e.preventDefault();
        return;
      }
      cleanup();
    }
  }

  document.addEventListener('mousemove', onMove, true);
  document.addEventListener('click', onClick, true);
  document.addEventListener('keydown', onKey, true);

  return { started: true, frameUrl: location.href, isTop: window === window.top };
}

/** Tear down annotate UI in every frame. */
export function annotateModeCleanupInjected(): void {
  const w = window as unknown as { __dsAnnotateCleanup?: () => void };
  if (typeof w.__dsAnnotateCleanup === 'function') {
    try {
      w.__dsAnnotateCleanup();
    } catch {
      /* ignore */
    }
  }
}
