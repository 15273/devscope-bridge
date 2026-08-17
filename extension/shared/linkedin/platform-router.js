/**
 * Detect LinkedIn surface from URL (ContactOut + Lusha + hireEZ patterns).
 */
(function () {
  'use strict';

  const TALENT_PROFILE_RE =
    /\/talent\/(?:profile|search\/profile|hire\/[^/]+\/[^/]+\/[^/]+\/profile)/i;
  const TALENT_SEARCH_RE =
    /\/talent\/(?:search|discover\/recruiterSearch|hire\/[^/]+\/(?:manage|discover))/i;

  function detectLinkedInSurface(url, _doc) {
    const href = String(url || (typeof location !== 'undefined' ? location.href : '')).toLowerCase();

    if (href.includes('linkedin.com/sales/search/people')) {
      return { id: 'sales_search', kind: 'search', bulk: true };
    }
    if (href.includes('linkedin.com/sales/people/') || href.includes('linkedin.com/sales/lead/')) {
      return { id: 'sales_profile', kind: 'profile', bulk: false };
    }
    if (href.includes('linkedin.com/sales/')) {
      return { id: 'sales_profile', kind: 'profile', bulk: false };
    }

    if (href.includes('linkedin.com/recruiter/smartsearch')) {
      return { id: 'recruiter_lite_search', kind: 'search', bulk: true };
    }
    if (href.includes('linkedin.com/recruiter/profile/')) {
      return { id: 'recruiter_lite_profile', kind: 'profile', bulk: false };
    }
    if (href.includes('linkedin.com/recruiter/')) {
      return { id: 'recruiter_lite_profile', kind: 'profile', bulk: false };
    }

    if (TALENT_PROFILE_RE.test(href)) {
      return { id: 'talent_profile', kind: 'profile', bulk: false };
    }
    if (href.includes('linkedin.com/talent/') && !href.includes('/profile')) {
      return { id: 'talent_search', kind: 'search', bulk: true };
    }
    if (TALENT_SEARCH_RE.test(href)) {
      return { id: 'talent_search', kind: 'search', bulk: true };
    }

    if (href.includes('/search/results/people')) {
      return { id: 'public_people_search', kind: 'search', bulk: true };
    }
    if (href.includes('/in/') || href.includes('/pub/')) {
      return { id: 'public_profile', kind: 'profile', bulk: false };
    }

    if (href.includes('linkedin.com/messaging')) {
      return { id: 'messaging', kind: 'other', bulk: false };
    }

    return { id: 'unknown', kind: 'other', bulk: false };
  }

  function isProfileSurface(surface) {
    return surface?.kind === 'profile';
  }

  function isSearchSurface(surface) {
    return surface?.kind === 'search';
  }

  window.__htLinkedInRouter = {
    detectLinkedInSurface,
    isProfileSurface,
    isSearchSurface,
    TALENT_PROFILE_RE,
  };
})();
