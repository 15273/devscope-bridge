/**
 * Talent / Recruiter search results scraper with card metadata.
 */
(function () {
  'use strict';

  function extractTalentRow(row, href, seen) {
    if (!href || seen.has(href)) return null;
    seen.add(href);
    const lines = window.__htLinkedInText.visibleLines(row);
    const query = window.__htLinkedInQuery;
    const name =
      query.textFromFirst(['[data-test-row-lockup-full-name]', '.artdeco-entity-lockup__title'], row) ||
      lines[0] ||
      '';
    const headline =
      query.textFromFirst(['[data-test-row-lockup-headline]'], row) || lines[1] || '';
    const location =
      query.textFromFirst(['[data-test-row-lockup-location]'], row) || lines[2] || '';
    const employer =
      query.textFromFirst(['[data-test-topcard-condensed-lockup-current-employer]'], row) ||
      lines[3] ||
      '';

    return {
      name,
      headline,
      location,
      current_company: employer,
      page_url: href,
      linkedin_url: href,
      card_lines: lines.slice(0, 8),
      surface: 'talent_search',
    };
  }

  async function scrapeTalentSearch(maxProfiles = 120) {
    const registry = window.__htLinkedInRegistry;
    const query = window.__htLinkedInQuery;
    const bulk = window.__htLinkedInBulkReveal;
    const parsers = window.__htLinkedInApiParsers;
    const normalizer = window.__htLinkedInNormalizer;
    const surface = { id: 'talent_search' };

    await window.__htLinkedInReadiness?.waitForSurfaceReady('talent_search');

    const profiles = [];
    const seen = new Set();

    const apiHits = parsers?.parseFromCache('talent_search_hits');
    if (apiHits?.length) {
      for (const hit of apiHits.slice(0, maxProfiles)) {
        profiles.push(
          normalizer.normalizeSearchCard(
            {
              ...hit,
              card_lines: [hit.name, hit.headline].filter(Boolean),
              surface: 'talent_search',
            },
            surface,
          ),
        );
      }
      return profiles;
    }

    const sel = registry?.getSurfaceSelectors('talent_search') || {};
    await bulk?.revealPendingRows(sel.result_row, sel.profile_link);

    const { elements: rows } = query.queryAllFirst(sel.result_row || []);
    for (const row of rows) {
      if (profiles.length >= maxProfiles) break;
      const href = query.hrefFromFirst(sel.profile_link, row);
      const card = extractTalentRow(row, href, seen);
      if (card) profiles.push(normalizer.normalizeSearchCard(card, surface));
    }
    return profiles;
  }

  window.__htLinkedInTalentSearch = { scrapeTalentSearch };
})();
