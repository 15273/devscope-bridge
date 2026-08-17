/**
 * Poll until surface-ready indicators appear (Lusha/SeekOut pattern).
 */
(function () {
  'use strict';

  async function waitForSurfaceReady(surfaceId, opts = {}) {
    const registry = window.__htLinkedInRegistry;
    const query = window.__htLinkedInQuery;
    const delay = window.__htLinkedInText?.delay || ((ms) => new Promise((r) => setTimeout(r, ms)));

    const indicators = opts.selectors ||
      registry?.READY_INDICATORS?.[surfaceId] ||
      ['main'];

    const maxAttempts = opts.maxAttempts || 60;
    const intervalMs = opts.intervalMs || 250;

    for (let i = 0; i < maxAttempts; i++) {
      const { element } = query.queryFirst(indicators);
      if (element) {
        const loaderSel = registry?.SELECTORS?.[surfaceId]?.loader;
        if (loaderSel) {
          const { element: loading } = query.queryFirst(loaderSel);
          if (loading && loading.offsetParent !== null) {
            await delay(intervalMs);
            continue;
          }
        }
        return true;
      }
      await delay(intervalMs);
    }
    return false;
  }

  async function waitForPublicProfileLink(selectors, timeoutMs = 10000) {
    const query = window.__htLinkedInQuery;
    const text = window.__htLinkedInText;
    const delay = text?.delay || ((ms) => new Promise((r) => setTimeout(r, ms)));
    const list = selectors || [
      'a[data-test-personal-info-profile-link]',
      '[data-test-public-profile-link]',
      '.public-profile a',
    ];
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
      const href = query.hrefFromFirst(list);
      const normalized = text?.normalizePublicProfileUrl(href);
      if (normalized) return normalized;
      await delay(200);
    }
    return null;
  }

  window.__htLinkedInReadiness = {
    waitForSurfaceReady,
    waitForPublicProfileLink,
  };
})();
