/**
 * Sales Navigator profile scraper (DOM + salesApi intercept).
 */
(function () {
  'use strict';

  function scrapeSalesProfile() {
    const registry = window.__htLinkedInRegistry;
    const query = window.__htLinkedInQuery;
    const text = window.__htLinkedInText;
    const parsers = window.__htLinkedInApiParsers;
    const sel = registry?.getSurfaceSelectors('sales_profile') || {};

    const apiData = parsers?.parseFromCache('sales_profile');
    if (apiData?.full_name) {
      return {
        ...apiData,
        linkedin_url: location.href.split('?')[0],
        page_url: location.href,
        sales_profile_url: location.href.split('?')[0],
      };
    }

    const hits = {
      full_name: query.textFromFirst(sel.full_name),
      headline: query.textFromFirst(sel.headline),
      location: query.textFromFirst(sel.location),
    };

    const experience = [];
    const { elements: expItems } = query.queryAllFirst(sel.experience_item || []);
    for (const item of expItems.slice(0, 15)) {
      const lines = text.visibleLines(item);
      if (lines.length >= 2) {
        experience.push({
          title: lines[0],
          company: lines[1],
          duration: lines[2] || '',
          description: lines.slice(3).join(' '),
        });
      }
    }

    return {
      source: 'linkedin_profile',
      full_name: hits.full_name,
      headline: hits.headline,
      location: hits.location,
      linkedin_url: location.href.split('?')[0],
      page_url: location.href,
      sales_profile_url: location.href.split('?')[0],
      experience,
      scraped_via: 'dom',
      selector_hits: hits,
      extracted_at: new Date().toISOString(),
    };
  }

  async function scrapeSalesProfileAsync() {
    await window.__htLinkedInReadiness?.waitForSurfaceReady('sales_profile');
    return scrapeSalesProfile();
  }

  window.__htLinkedInSalesProfile = {
    scrapeSalesProfile,
    scrapeSalesProfileAsync,
  };
})();
