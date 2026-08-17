/**
 * Selector probe — tests registry chains on current page (diagnostics).
 */
(function () {
  'use strict';

  function probe() {
    const router = window.__htLinkedInRouter;
    const registry = window.__htLinkedInRegistry;
    const query = window.__htLinkedInQuery;
    const intercept = window.__htLinkedInIntercept;

    const surface = router.detectLinkedInSurface(location.href);
    const selectors = registry.getSurfaceSelectors(surface.id);
    const fields = {};

    for (const [field, chain] of Object.entries(selectors)) {
      if (field === 'ready' || field === 'loader') continue;
      const isLink = field.includes('link') || field.includes('url');
      if (isLink) {
        const href = query.hrefFromFirst(chain);
        fields[field] = {
          matched: Boolean(href),
          sample: href ? href.slice(0, 120) : null,
          selector: chain.find((s) => {
            try {
              return document.querySelector(s);
            } catch (_) {
              return false;
            }
          }) || null,
        };
      } else if (field === 'result_row' || field === 'experience_item') {
        const { elements, matchedSelector } = query.queryAllFirst(chain);
        fields[field] = {
          matched: elements.length > 0,
          count: elements.length,
          selector: matchedSelector,
        };
      } else {
        const { element, matchedSelector } = query.queryFirst(chain);
        const sample = element
          ? (query.textFromFirst([matchedSelector]) || element.textContent || '').slice(0, 80)
          : null;
        fields[field] = { matched: Boolean(element), sample, selector: matchedSelector };
      }
    }

    const apiRoutes = (intercept?.ROUTES || []).map((r) => ({
      key: r.key,
      cached: Boolean(intercept?.getLatest(r.key)),
    }));

    return {
      url: location.href,
      surface,
      fields,
      api_cache: apiRoutes,
      probed_at: new Date().toISOString(),
    };
  }

  window.__htLinkedInSelectorProbe = { probe };
})();
