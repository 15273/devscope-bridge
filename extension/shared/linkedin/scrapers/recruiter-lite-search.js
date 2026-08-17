/**
 * Recruiter Lite smartsearch scraper with card metadata.
 */
(function () {
  'use strict';

  async function scrapeRecruiterLiteSearch(maxProfiles = 120) {
    const registry = window.__htLinkedInRegistry;
    const normalizer = window.__htLinkedInNormalizer;
    const surface = { id: 'recruiter_lite_search' };

    await window.__htLinkedInReadiness?.waitForSurfaceReady('recruiter_lite_search');

    const profiles = [];
    const seen = new Set();

    for (const anchor of document.querySelectorAll(
      'a.search-result-profile-link, a[href*="/recruiter/profile/"]',
    )) {
      if (profiles.length >= maxProfiles) break;
      const href = anchor.href?.split('?')[0];
      if (!href || seen.has(href)) continue;
      seen.add(href);

      const container = anchor.closest('li') || anchor.parentElement;
      const lines = window.__htLinkedInText.visibleLines(container);
      const query = window.__htLinkedInQuery;
      const name =
        query.textFromFirst(['.name', '.search-result__info'], container) ||
        lines[0] ||
        anchor.textContent?.trim() ||
        '';

      profiles.push(
        normalizer.normalizeSearchCard(
          {
            name,
            headline: lines[1] || '',
            location: lines[2] || '',
            page_url: href,
            linkedin_url: href,
            recruiter_profile_url: href,
            card_lines: lines.slice(0, 8),
            surface: 'recruiter_lite_search',
          },
          surface,
        ),
      );
    }
    return profiles;
  }

  window.__htLinkedInRecruiterLiteSearch = { scrapeRecruiterLiteSearch };
})();
