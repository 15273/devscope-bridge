/**
 * Talent / Recruiter pipeline profile scraper (data-test-* selectors).
 */
(function () {
  'use strict';

  function scrapeTalentProfile() {
    const registry = window.__htLinkedInRegistry;
    const query = window.__htLinkedInQuery;
    const text = window.__htLinkedInText;
    const parsers = window.__htLinkedInApiParsers;
    const sel = registry?.getSurfaceSelectors('talent_profile') || {};
    const hits = {};

    const apiData = parsers?.parseFromCache('talent_profile');
    if (apiData?.full_name) {
      return {
        ...apiData,
        linkedin_url: location.href.split('?')[0],
        page_url: location.href,
        talent_profile_url: location.href.split('?')[0],
        public_linkedin_url: apiData.public_linkedin_url,
        scraped_via: 'api',
      };
    }

    hits.full_name = query.textFromFirst(sel.full_name);
    hits.headline = query.textFromFirst(sel.headline);
    hits.location = query.textFromFirst(sel.location);
    hits.public_profile_link = query.hrefFromFirst(sel.public_profile_link);

    const experience = [];
    const { elements: expItems } = query.queryAllFirst(sel.experience_item || []);
    for (const item of expItems.slice(0, 20)) {
      const lines = text.visibleLines(item);
      if (lines.length) {
        experience.push({
          title: lines[0] || '',
          company: lines[1] || '',
          duration: lines.find((l) => /\d{4}|present|נוכחי/i.test(l)) || '',
          description: lines.slice(2).join(' '),
        });
      }
    }

    const publicUrl = text.normalizePublicProfileUrl(hits.public_profile_link);

    return {
      source: 'linkedin_profile',
      full_name: hits.full_name,
      headline: hits.headline,
      location: hits.location,
      linkedin_url: publicUrl || location.href.split('?')[0],
      page_url: location.href,
      talent_profile_url: location.href.split('?')[0],
      public_linkedin_url: publicUrl || undefined,
      experience,
      scraped_via: 'dom',
      selector_hits: hits,
      extracted_at: new Date().toISOString(),
    };
  }

  async function scrapeTalentProfileAsync() {
    const readiness = window.__htLinkedInReadiness;
    await readiness?.waitForSurfaceReady('talent_profile');
    let profile = scrapeTalentProfile();
    if (!profile.public_linkedin_url && readiness?.waitForPublicProfileLink) {
      const publicUrl = await readiness.waitForPublicProfileLink(
        window.__htLinkedInRegistry?.SELECTORS?.talent_profile?.public_profile_link,
      );
      if (publicUrl) {
        profile.public_linkedin_url = publicUrl;
        profile.linkedin_url = publicUrl;
      }
    }
    return profile;
  }

  window.__htLinkedInTalentProfile = {
    scrapeTalentProfile,
    scrapeTalentProfileAsync,
  };
})();
