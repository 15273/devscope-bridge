/**
 * Compose full LinkedIn search page state (surface, facets, pills, counts).
 */
(function () {
  'use strict';

  function readSearchPageState(options = {}) {
    const router = window.__htLinkedInRouter;
    const facets = window.__htLinkedInFacetParser;
    const pills = window.__htLinkedInFilterPills;
    const surface = router?.detectLinkedInSurface?.(location.href) || { id: 'unknown' };

    const urlFacets = facets?.parseSearchUrlFacets?.(location.href) || {
      raw: {},
      facets: [],
      keywords: '',
      origin: null,
    };

    const filterPills = pills?.readActiveFilterPills?.() || [];
    const allPills = pills?.readFilterPills?.() || [];
    const resultsHeading = pills?.readResultsHeading?.() || '';

    let visibleCards = 0;
    let page = '1';

    if (surface.id === 'public_people_search' && window.__htLinkedInPublicSearch) {
      const rows = document.querySelectorAll('main [role="listitem"] a[href*="/in/"]');
      visibleCards = rows.length || window.__htLinkedInPublicSearch.scrapeVisibleCards(new Set(), 999).length;
      page = document.querySelector('button[aria-current="page"]')?.textContent?.trim() || '1';
    }

    const state = {
      page_url: location.href.split('#')[0],
      surface: surface.id,
      surface_kind: surface.kind,
      keywords: urlFacets.keywords || new URLSearchParams(location.search).get('keywords') || '',
      origin: urlFacets.origin,
      url_facets: urlFacets.facets,
      url_facets_raw: urlFacets.raw,
      facet_summary: facets?.facetsToSummary?.(urlFacets.facets) || '',
      filter_pills: filterPills,
      all_filter_pills: allPills,
      active_filter_labels: filterPills.map((p) => p.label),
      results_heading: resultsHeading,
      visible_cards: visibleCards,
      page,
      captured_at: new Date().toISOString(),
    };

    if (options.includeInactivePills === false) {
      delete state.all_filter_pills;
    }

    return state;
  }

  window.__htLinkedInSearchState = {
    readSearchPageState,
  };
})();
