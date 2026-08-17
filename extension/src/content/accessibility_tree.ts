/**
 * accessibility_tree.ts — persistent ref map on every page (Claude parity).
 * Exposes window.__devscopeGenerateAccessibilityTree for the background snapshot tool.
 */

const MAX_NODES = 400;
const INTERACTIVE =
  'a,button,input,select,textarea,[role],[aria-haspopup],[aria-expanded],[data-testid],h1,h2,h3,nav,main,header,footer,form,[contenteditable="true"],[class*="awsui-"]';

interface SnapshotNode {
  ref: number;
  role: string;
  tag: string;
  name: string;
  selector?: string;
  bbox?: { x: number; y: number; width: number; height: number };
  href?: string;
  value?: string;
  'aria-expanded'?: string;
  'data-testid'?: string;
}

function buildSelector(el: Element): string {
  if (el.id) return `#${CSS.escape(el.id)}`;
  const testId = el.getAttribute('data-testid');
  if (testId) return `[data-testid="${CSS.escape(testId)}"]`;
  const parts: string[] = [];
  let cur: Element | null = el;
  let depth = 0;
  while (cur && cur !== document.documentElement && depth < 5) {
    let part = cur.tagName.toLowerCase();
    const parent = cur.parentElement;
    if (parent) {
      const siblings = Array.from(parent.children).filter((c) => c.tagName === cur!.tagName);
      if (siblings.length > 1) {
        part += `:nth-of-type(${siblings.indexOf(cur) + 1})`;
      }
    }
    parts.unshift(part);
    cur = parent;
    depth += 1;
  }
  return parts.join(' > ');
}

function generateTree(): { frameUrl: string; count: number; elements: SnapshotNode[] } | null {
  const map = new Map<number, Element>();
  const elements: SnapshotNode[] = [];
  let nextRef = 1;

  for (const el of Array.from(document.querySelectorAll(INTERACTIVE))) {
    if (elements.length >= MAX_NODES) break;
    const rect = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    if (rect.width === 0 || rect.height === 0 || style.visibility === 'hidden' || style.display === 'none') {
      continue;
    }
    const ref = nextRef++;
    map.set(ref, el);
    const item: SnapshotNode = {
      ref,
      role: el.getAttribute('role') ?? el.tagName.toLowerCase(),
      tag: el.tagName.toLowerCase(),
      name: (
        el.getAttribute('aria-label') ??
        el.getAttribute('placeholder') ??
        el.getAttribute('alt') ??
        (el.textContent ?? '').trim()
      ).slice(0, 120),
      selector: buildSelector(el),
      bbox: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
    };
    const href = el.getAttribute('href');
    if (href) item.href = href;
    const val = (el as HTMLInputElement).value;
    if (typeof val === 'string' && val) item.value = val.slice(0, 120);
    const expanded = el.getAttribute('aria-expanded');
    if (expanded != null) item['aria-expanded'] = expanded;
    const testId = el.getAttribute('data-testid');
    if (testId) item['data-testid'] = testId;
    elements.push(item);
  }

  if (elements.length === 0) return null;

  (window as unknown as { __devscopeElementMap?: Map<number, Element> }).__devscopeElementMap = map;
  return { frameUrl: location.href, count: elements.length, elements };
}

(window as unknown as { __devscopeGenerateAccessibilityTree?: () => ReturnType<typeof generateTree> }).__devscopeGenerateAccessibilityTree =
  generateTree;

export {};
