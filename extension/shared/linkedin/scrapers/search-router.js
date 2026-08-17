/**
 * Search scrape router — dispatches by detected LinkedIn surface.
 */
(function () {
  'use strict';

  function countScrapeSources(profiles) {
    const core = window.__htLinkedInPeopleSearchCore;
    if (core?.countScrapeSources) return core.countScrapeSources(profiles);
    const counts = { page_json: 0, api: 0, dom: 0, mixed: 0 };
    for (const p of profiles || []) {
      const via = p.scraped_via || 'dom';
      if (counts[via] != null) counts[via] += 1;
      else counts.dom += 1;
    }
    return counts;
  }

  function attachSearchState(data, surface) {
    const stateReader = window.__htLinkedInSearchState?.readSearchPageState;
    const searchState = stateReader ? stateReader() : { surface: surface?.id };
    const profiles = data.profiles || [];
    return {
      ...data,
      search_state: searchState,
      scrape_sources: countScrapeSources(profiles),
    };
  }

  async function scrapeSearch(opts = {}) {
    const router = window.__htLinkedInRouter;
    const surface = router.detectLinkedInSurface(location.href);
    const maxProfiles = Math.min(Number(opts.maxProfiles) || 120, 150);

    switch (surface.id) {
      case 'public_people_search': {
        const pub = window.__htLinkedInPublicSearch;
        if (opts.deep) {
          const profiles = await pub.deepScrapeSearch(
            maxProfiles,
            Math.min(Number(opts.maxPages) || 12, 20),
          );
          return attachSearchState(
            {
              profiles,
              surface: surface.id,
              deep: true,
            },
            surface,
          );
        }
        return attachSearchState(
          {
            profiles: pub.scrapeVisibleCards(new Set(), 25),
            surface: surface.id,
          },
          surface,
        );
      }
      case 'talent_search':
        return attachSearchState(
          {
            profiles: await window.__htLinkedInTalentSearch.scrapeTalentSearch(maxProfiles),
            surface: surface.id,
            deep: Boolean(opts.deep),
          },
          surface,
        );
      case 'sales_search':
        return attachSearchState(
          {
            profiles: await window.__htLinkedInSalesSearch.scrapeSalesSearch(maxProfiles),
            surface: surface.id,
            deep: Boolean(opts.deep),
          },
          surface,
        );
      case 'recruiter_lite_search':
        return attachSearchState(
          {
            profiles: await window.__htLinkedInRecruiterLiteSearch.scrapeRecruiterLiteSearch(maxProfiles),
            surface: surface.id,
            deep: Boolean(opts.deep),
          },
          surface,
        );
      default:
        throw new Error(`Unsupported search surface: ${surface.id}`);
    }
  }

  function readSearchState() {
    if (window.__htLinkedInSearchState?.readSearchPageState) {
      return window.__htLinkedInSearchState.readSearchPageState();
    }
    const surface = window.__htLinkedInRouter.detectLinkedInSurface(location.href);
    return { page_url: location.href, surface: surface.id };
  }

  window.__htLinkedInSearchRouter = {
    scrapeSearch,
    readSearchState,
    countScrapeSources,
  };
})();
