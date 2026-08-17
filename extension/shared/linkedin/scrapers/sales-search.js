/**
 * Sales Navigator people search scraper with card metadata.
 */
(function () {
  'use strict';

  function extractSalesRow(row, href, seen) {
    if (!href || seen.has(href)) return null;
    seen.add(href);
    const lines = window.__htLinkedInText.visibleLines(row);
    const query = window.__htLinkedInQuery;
    const name =
      query.textFromFirst(['[data-anonymize="person-name"]', '.result-lockup__name'], row) ||
      lines[0] ||
      '';
    const headline =
      query.textFromFirst(['[data-anonymize="headline"]', '.result-lockup__highlight-keyword'], row) ||
      lines[1] ||
      '';
    const location =
      query.textFromFirst(['[data-anonymize="location"]'], row) || lines[2] || '';

    return {
      name,
      headline,
      location,
      page_url: href,
      linkedin_url: href,
      sales_profile_url: href,
      card_lines: lines.slice(0, 8),
      surface: 'sales_search',
    };
  }

  async function scrapeSalesSearch(maxProfiles = 120) {
    const registry = window.__htLinkedInRegistry;
    const query = window.__htLinkedInQuery;
    const bulk = window.__htLinkedInBulkReveal;
    const parsers = window.__htLinkedInApiParsers;
    const normalizer = window.__htLinkedInNormalizer;
    const surface = { id: 'sales_search' };

    await window.__htLinkedInReadiness?.waitForSurfaceReady('sales_search');

    const profiles = [];
    const seen = new Set();

    const apiHits = parsers?.parseFromCache('sales_people_search');
    if (apiHits?.length) {
      for (const hit of apiHits.slice(0, maxProfiles)) {
        profiles.push(
          normalizer.normalizeSearchCard(
            {
              name: hit.name,
              headline: hit.headline,
              page_url: hit.sales_profile_url,
              linkedin_url: hit.sales_profile_url,
              sales_profile_url: hit.sales_profile_url,
              card_lines: [hit.name, hit.headline].filter(Boolean),
              surface: 'sales_search',
            },
            surface,
          ),
        );
      }
      return profiles;
    }

    const sel = registry?.getSurfaceSelectors('sales_search') || {};
    await bulk?.revealPendingRows(sel.result_row, sel.profile_link);

    const { elements: rows } = query.queryAllFirst(sel.result_row || []);
    for (const row of rows) {
      if (profiles.length >= maxProfiles) break;
      const href = query.hrefFromFirst(sel.profile_link, row);
      const card = extractSalesRow(row, href, seen);
      if (card) profiles.push(normalizer.normalizeSearchCard(card, surface));
    }
    return profiles;
  }

  window.__htLinkedInSalesSearch = { scrapeSalesSearch };
})();
