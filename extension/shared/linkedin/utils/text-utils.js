/**
 * Shared text cleaning helpers for LinkedIn scrapers.
 */
(function () {
  'use strict';

  const BIDI = /[‎‏‪-‮⁦-⁩]/g;
  const SEE_MORE = /^…?\s*(more|see more|show more|עוד|ראה עוד|הצג עוד)\s*…?$/i;

  function cleanLine(v) {
    return String(v || '').replace(BIDI, '').replace(/\s+/g, ' ').trim();
  }

  function visibleLines(el) {
    if (!el) return [];
    const raw = el.innerText || el.textContent || '';
    const lines = [];
    let prev = '';
    for (const part of raw.split('\n')) {
      const line = cleanLine(part);
      if (!line || line === prev || SEE_MORE.test(line)) continue;
      lines.push(line);
      prev = line;
    }
    return lines;
  }

  function ariaText(scope, selector) {
    const root = selector ? scope.querySelector(selector) : scope;
    if (!root) return '';
    const el = root.matches?.('span[aria-hidden="true"]')
      ? root
      : root.querySelector('span[aria-hidden="true"]');
    return cleanLine(el?.textContent || '');
  }

  function delay(ms) {
    return new Promise((r) => setTimeout(r, ms));
  }

  function normalizePublicProfileUrl(href) {
    try {
      const url = new URL(href, 'https://www.linkedin.com');
      if (!url.pathname.includes('/in/')) return null;
      let path = url.pathname;
      if (!path.endsWith('/')) path += '/';
      return `https://www.linkedin.com${path}`;
    } catch (_) {
      return null;
    }
  }

  function slugFromUrl(url) {
    const m = String(url || '').match(/\/in\/([^/]+)\//);
    return m ? m[1] : url;
  }

  window.__htLinkedInText = {
    cleanLine,
    visibleLines,
    ariaText,
    delay,
    normalizePublicProfileUrl,
    slugFromUrl,
    SEE_MORE,
  };
})();
