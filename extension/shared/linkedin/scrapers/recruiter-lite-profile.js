/**
 * Recruiter Lite profile scraper — maps to public /in/ URL when available.
 */
(function () {
  'use strict';

  async function scrapeRecruiterLiteProfile() {
    const registry = window.__htLinkedInRegistry;
    const query = window.__htLinkedInQuery;
    const text = window.__htLinkedInText;
    const readiness = window.__htLinkedInReadiness;
    const sel = registry?.getSurfaceSelectors('recruiter_lite_profile') || {};

    await readiness?.waitForSurfaceReady('recruiter_lite_profile');

    const hits = {
      full_name: query.textFromFirst(sel.full_name),
      headline: query.textFromFirst(sel.headline),
      public_profile_link: query.hrefFromFirst(sel.public_profile_link),
    };

    let publicUrl = text.normalizePublicProfileUrl(hits.public_profile_link);
    if (!publicUrl && readiness?.waitForPublicProfileLink) {
      publicUrl = await readiness.waitForPublicProfileLink(sel.public_profile_link);
    }

    return {
      source: 'linkedin_profile',
      full_name: hits.full_name,
      headline: hits.headline,
      linkedin_url: publicUrl || location.href.split('?')[0],
      page_url: location.href,
      public_linkedin_url: publicUrl || undefined,
      scraped_via: 'dom',
      selector_hits: hits,
      extracted_at: new Date().toISOString(),
    };
  }

  window.__htLinkedInRecruiterLiteProfile = {
    scrapeRecruiterLiteProfile,
  };
})();
