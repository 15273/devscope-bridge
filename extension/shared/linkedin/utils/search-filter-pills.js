/**
 * Read LinkedIn active filter pills from search UI (public + talent + sales patterns).
 */
(function () {
  'use strict';

  const PILL_SELECTORS = [
    'button.search-reusables__filter-pill-button',
    '.search-reusables__filters-bar button',
    'ul.search-reusables__filter-list button',
    'main button.artdeco-pill',
    '.search-filters-bar button.artdeco-pill',
    '[data-test-filter-pill]',
    '.artdeco-pill--selected',
    '.search-results__filter-pill',
    '.talent-search-filters button',
    '.facet-pill',
  ];

  function cleanLabel(text) {
    return String(text || '')
      .replace(/\s+/g, ' ')
      .replace(/^Filter by\s+/i, '')
      .trim()
      .slice(0, 120);
  }

  function isActivePill(btn) {
    if (!btn) return false;
    return (
      btn.getAttribute('aria-pressed') === 'true' ||
      btn.classList.contains('artdeco-pill--selected') ||
      btn.classList.contains('search-reusables__filter-pill-button--selected') ||
      btn.getAttribute('aria-checked') === 'true' ||
      btn.hasAttribute('data-test-filter-pill-active')
    );
  }

  function readFilterPills(root) {
    const scope = root || document;
    const pills = [];
    const seen = new Set();

    for (const sel of PILL_SELECTORS) {
      for (const btn of scope.querySelectorAll(sel)) {
        const label = cleanLabel(btn.innerText || btn.textContent || btn.getAttribute('aria-label'));
        if (!label || label.length < 2 || seen.has(label)) continue;
        seen.add(label);
        pills.push({
          label,
          active: isActivePill(btn),
          selector: sel,
        });
      }
    }
    return pills;
  }

  function readActiveFilterPills(root) {
    return readFilterPills(root).filter((p) => p.active);
  }

  function readResultsHeading(root) {
    const scope = root || document;
    const el =
      scope.querySelector('.search-results-container h1') ||
      scope.querySelector('.search-results-container h2') ||
      scope.querySelector('main h1') ||
      scope.querySelector('[data-test-search-results-header]');
    return (el?.innerText || '').trim().slice(0, 200);
  }

  window.__htLinkedInFilterPills = {
    readFilterPills,
    readActiveFilterPills,
    readResultsHeading,
  };
})();
