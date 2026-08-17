/**
 * Normalize surface-specific scrape → unified LinkedInProfileData + _meta.
 */
(function () {
  'use strict';

  function buildMeta(surface, extra = {}) {
    return {
      surface: surface?.id || 'unknown',
      page_url: typeof location !== 'undefined' ? location.href.split('?')[0] : '',
      scraped_at: new Date().toISOString(),
      ...extra,
    };
  }

  function normalizeProfile(raw, surface, selectorHits = {}) {
    const text = window.__htLinkedInText;
    const publicUrl =
      text?.normalizePublicProfileUrl(raw.public_linkedin_url || raw.linkedin_url) ||
      (raw.linkedin_url?.includes('/in/') ? raw.linkedin_url : null);

    const profile = {
      source: 'linkedin_profile',
      linkedin_url: publicUrl || raw.linkedin_url || raw.page_url || '',
      full_name: raw.full_name || raw.name || '',
      headline: raw.headline || '',
      location: raw.location || '',
      photo_url: raw.photo_url || undefined,
      about: raw.about || '',
      experience: raw.experience || [],
      education: raw.education || [],
      skills: raw.skills || [],
      certifications: raw.certifications || [],
      projects: raw.projects || [],
      languages: raw.languages || [],
      volunteering: raw.volunteering || [],
      honors: raw.honors || [],
      recommendations_received: raw.recommendations_received || [],
      activity_posts: raw.activity_posts || [],
      raw_text: raw.raw_text || '',
      extracted_at: raw.extracted_at || new Date().toISOString(),
      surface: surface?.id || raw.surface || 'unknown',
      page_url: raw.page_url || (typeof location !== 'undefined' ? location.href : ''),
      public_linkedin_url: publicUrl || undefined,
      _meta: buildMeta(surface, {
        scraped_via: raw.scraped_via || 'dom',
        selector_hits: selectorHits,
        sales_profile_url: raw.sales_profile_url,
        talent_profile_url: raw.talent_profile_url,
        member_urn: raw.member_urn,
      }),
    };

    if (!profile.raw_text && profile.full_name) {
      const parts = [
        profile.full_name,
        profile.headline,
        profile.location,
        profile.about,
      ].filter(Boolean);
      profile.raw_text = parts.join('\n').slice(0, 15000);
    }

    return profile;
  }

  function normalizeSearchCard(card, surface) {
    const text = window.__htLinkedInText;
    const linkedin_url =
      text?.normalizePublicProfileUrl(card.linkedin_url || card.profile_url || '') ||
      card.linkedin_url ||
      card.page_url ||
      '';

    return {
      linkedin_url,
      name: card.name || card.full_name || '',
      headline: card.headline || '',
      location: card.location || '',
      photo_url: card.photo_url,
      connection_degree: card.connection_degree,
      current_company: card.current_company,
      mutual_connections: card.mutual_connections,
      open_to_work: card.open_to_work,
      is_hiring: card.is_hiring,
      result_urn: card.result_urn,
      card_lines: card.card_lines,
      page_url: card.page_url || linkedin_url,
      sales_profile_url: card.sales_profile_url,
      recruiter_profile_url: card.recruiter_profile_url,
      surface: surface?.id || card.surface || 'unknown',
    };
  }

  window.__htLinkedInNormalizer = {
    normalizeProfile,
    normalizeSearchCard,
    buildMeta,
  };
})();
