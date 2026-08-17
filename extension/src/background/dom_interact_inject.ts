/**
 * dom_interact_inject.ts — page-context DOM helpers injected via executeScript.
 *
 * Must stay self-contained: Chrome serializes a single function; no imports from
 * other modules inside the injected closure.
 */

/** Dispatch click / pointer / keyboard open sequence for React & Cloudscape widgets. */
export function injectedDomAction(
  action: 'click' | 'select_option' | 'hover',
  selector: string,
  value?: string,
): Record<string, unknown> | Promise<Record<string, unknown>> {
  function center(el: Element): { x: number; y: number } {
    const r = el.getBoundingClientRect();
    return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
  }

  function pointerOpts(el: Element, type: string): PointerEventInit {
    const { x, y } = center(el);
    return {
      bubbles: true,
      cancelable: true,
      composed: true,
      view: window,
      clientX: x,
      clientY: y,
      button: 0,
      buttons: type.includes('down') ? 1 : 0,
      pointerId: 1,
      pointerType: 'mouse',
      isPrimary: true,
    };
  }

  function mouseOpts(el: Element, type: string): MouseEventInit {
    const { x, y } = center(el);
    return {
      bubbles: true,
      cancelable: true,
      composed: true,
      view: window,
      clientX: x,
      clientY: y,
      button: 0,
      buttons: type.includes('down') ? 1 : 0,
    };
  }

  function isVisible(el: Element): boolean {
    const style = window.getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden' || style.pointerEvents === 'none') {
      return false;
    }
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  }

  function scrollAndFocus(el: HTMLElement): void {
    el.scrollIntoView({ block: 'center', inline: 'center', behavior: 'instant' as ScrollBehavior });
    if (!el.matches(':focus-visible') && typeof el.focus === 'function') {
      try {
        el.focus({ preventScroll: true });
      } catch {
        el.focus();
      }
    }
  }

  function dispatchPointerClick(el: HTMLElement): void {
    scrollAndFocus(el);
    const seq: Array<[string, EventInit]> = [
      ['pointerover', pointerOpts(el, 'over')],
      ['pointerenter', pointerOpts(el, 'enter')],
      ['mouseover', mouseOpts(el, 'over')],
      ['mouseenter', mouseOpts(el, 'enter')],
      ['pointerdown', pointerOpts(el, 'down')],
      ['mousedown', mouseOpts(el, 'down')],
      ['pointerup', pointerOpts(el, 'up')],
      ['mouseup', mouseOpts(el, 'up')],
    ];
    for (const [type, init] of seq) {
      const Ctor = type.startsWith('pointer') ? PointerEvent : MouseEvent;
      el.dispatchEvent(new Ctor(type, init));
    }
    // Exactly ONE click event: a coordinate-carrying dispatch followed by
    // el.click() fired TWO clicks per call, instantly closing toggle UIs
    // (menus, dropdowns) that open on the first click.
    el.dispatchEvent(new MouseEvent('click', mouseOpts(el, 'click')));
  }

  function ariaExpanded(el: Element): string | null {
    return el.getAttribute('aria-expanded');
  }

  function maybeOpenCombobox(el: HTMLElement): void {
    const role = el.getAttribute('role') ?? '';
    const tag = el.tagName.toLowerCase();
    if (role === 'combobox' || role === 'button' || el.getAttribute('aria-haspopup') != null) {
      if (ariaExpanded(el) !== 'true') {
        dispatchPointerClick(el);
        el.dispatchEvent(
          new KeyboardEvent('keydown', { key: 'ArrowDown', code: 'ArrowDown', bubbles: true, cancelable: true }),
        );
        el.dispatchEvent(
          new KeyboardEvent('keyup', { key: 'ArrowDown', code: 'ArrowDown', bubbles: true, cancelable: true }),
        );
      }
    } else if (tag === 'select') {
      el.dispatchEvent(new MouseEvent('mousedown', mouseOpts(el, 'down')));
    }
  }

  function normalize(s: string): string {
    return s.trim().toLowerCase().replace(/\s+/g, ' ');
  }

  function optionMatches(el: Element, needle: string): boolean {
    const n = normalize(needle);
    const text = normalize(el.getAttribute('aria-label') ?? el.textContent ?? '');
    const val = normalize(el.getAttribute('data-value') ?? el.getAttribute('value') ?? '');
    return text === n || val === n || text.includes(n);
  }

  function findListbox(trigger: HTMLElement): Element | null {
    const controls = trigger.getAttribute('aria-controls');
    if (controls) {
      const byId = document.getElementById(controls);
      if (byId && isVisible(byId)) return byId;
    }
    const owned = trigger.getAttribute('aria-owns');
    if (owned) {
      const byOwns = document.getElementById(owned);
      if (byOwns && isVisible(byOwns)) return byOwns;
    }
    const near = trigger.closest('[class*="awsui"], [class*="cloudscape"], form, section, div');
    if (near) {
      const local = near.querySelector('[role="listbox"]:not([aria-hidden="true"])');
      if (local && isVisible(local)) return local;
    }
    for (const lb of document.querySelectorAll('[role="listbox"]')) {
      if (isVisible(lb)) return lb;
    }
    return null;
  }

  function findOption(needle: string, scope?: Element | Document): HTMLElement | null {
    const root = scope ?? document;
    const sel =
      '[role="option"], [role="menuitemradio"], [role="menuitem"], [class*="awsui-select-option"], [class*="dropdown-option"]';
    for (const el of root.querySelectorAll(sel)) {
      if (!isVisible(el)) continue;
      if (optionMatches(el, needle)) return el as HTMLElement;
    }
    return null;
  }

  function resolveTrigger(sel: string): HTMLElement | null {
    const el = document.querySelector(sel);
    if (!el) return null;
    if (el instanceof HTMLElement) {
      return (
        (el.closest('[role="combobox"]') as HTMLElement | null) ??
        (el.closest('button,[role="button"]') as HTMLElement | null) ??
        el
      );
    }
    return null;
  }

  function readState(el: HTMLElement): Record<string, unknown> {
    return {
      tag: el.tagName.toLowerCase(),
      role: el.getAttribute('role'),
      ariaExpanded: ariaExpanded(el),
      ariaControls: el.getAttribute('aria-controls'),
      frameUrl: location.href,
    };
  }

  if (action === 'hover') {
    const el = document.querySelector(selector);
    if (!el || !(el instanceof HTMLElement)) return { error: `Element not found: ${selector}` };
    scrollAndFocus(el);
    el.dispatchEvent(new PointerEvent('pointerover', pointerOpts(el, 'over')));
    el.dispatchEvent(new MouseEvent('mouseover', mouseOpts(el, 'over')));
    el.dispatchEvent(new MouseEvent('mouseenter', mouseOpts(el, 'enter')));
    return { ok: true, selector, ...readState(el) };
  }

  if (action === 'click') {
    const el = document.querySelector(selector);
    if (!el || !(el instanceof HTMLElement)) return { error: `Element not found: ${selector}` };
    const before = ariaExpanded(el);
    dispatchPointerClick(el);
    const after = ariaExpanded(el);
    const { x, y } = center(el);
    const top = document.elementFromPoint(x, y);
    return {
      success: true,
      selector,
      ...readState(el),
      ariaExpandedBefore: before,
      ariaExpandedAfter: after,
      hitTarget: top ? { tag: top.tagName.toLowerCase(), id: top.id || undefined } : null,
    };
  }

  if (action === 'select_option') {
    const needle = value ?? '';
    if (!needle) return { error: 'value is required (option value or visible label text)' };

    const direct = document.querySelector(selector) as HTMLSelectElement | null;
    if (direct?.tagName.toLowerCase() === 'select') {
      const opt = Array.from(direct.options).find(
        (o) => o.value === needle || normalize(o.textContent ?? '') === normalize(needle),
      );
      if (!opt) return { error: `No option matching "${needle}" in ${selector}` };
      direct.value = opt.value;
      direct.dispatchEvent(new Event('input', { bubbles: true }));
      direct.dispatchEvent(new Event('change', { bubbles: true }));
      return { ok: true, mode: 'native-select', selector, value: opt.value, label: opt.textContent?.trim() };
    }

    const trigger = resolveTrigger(selector);
    if (!trigger) return { error: `Element not found: ${selector}` };

    return new Promise<Record<string, unknown>>((resolve) => {
      const start = Date.now();
      const timeoutMs = 3000;

      const attempt = (): void => {
        maybeOpenCombobox(trigger);
        const listbox = findListbox(trigger);
        const option = findOption(needle, listbox ?? document);
        if (option) {
          dispatchPointerClick(option);
          resolve({
            ok: true,
            mode: 'aria-listbox',
            selector,
            value: needle,
            matchedText: (option.textContent ?? '').trim().slice(0, 120),
            ariaExpandedAfter: ariaExpanded(trigger),
            waitedMs: Date.now() - start,
          });
          return;
        }
        if (Date.now() - start >= timeoutMs) {
          resolve({
            error: `No visible option matching "${needle}" after opening dropdown (selector=${selector}). ` +
              'Try browser_get_elements on [role="option"] or browser_snapshot with aria-expanded.',
            ariaExpanded: ariaExpanded(trigger),
            waitedMs: Date.now() - start,
          });
          return;
        }
        setTimeout(attempt, 120);
      };

      attempt();
    });
  }

  return { error: `Unknown action: ${action}` };
}
