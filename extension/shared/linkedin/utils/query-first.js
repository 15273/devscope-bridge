/**
 * Walk selector priority chains — first match wins.
 */
(function () {
  'use strict';

  function queryFirst(selectors, root) {
    const scope = root || document;
    const list = Array.isArray(selectors) ? selectors : [selectors];
    for (const sel of list) {
      if (!sel) continue;
      try {
        const el = scope.querySelector(sel);
        if (el) return { element: el, matchedSelector: sel };
      } catch (_) {
        /* invalid selector */
      }
    }
    return { element: null, matchedSelector: null };
  }

  function queryAllFirst(selectors, root) {
    const scope = root || document;
    const list = Array.isArray(selectors) ? selectors : [selectors];
    for (const sel of list) {
      if (!sel) continue;
      try {
        const nodes = scope.querySelectorAll(sel);
        if (nodes?.length) return { elements: Array.from(nodes), matchedSelector: sel };
      } catch (_) {
        /* skip */
      }
    }
    return { elements: [], matchedSelector: null };
  }

  function textFromFirst(selectors, root) {
    const { element } = queryFirst(selectors, root);
    if (!element) return '';
    const text = window.__htLinkedInText;
    return text?.ariaText(element) || text?.cleanLine(element.textContent) || '';
  }

  function hrefFromFirst(selectors, root) {
    const { element } = queryFirst(selectors, root);
    if (!element) return '';
    const href = element.href || element.getAttribute('href') || '';
    return href.split('?')[0];
  }

  window.__htLinkedInQuery = {
    queryFirst,
    queryAllFirst,
    textFromFirst,
    hrefFromFirst,
  };
})();
