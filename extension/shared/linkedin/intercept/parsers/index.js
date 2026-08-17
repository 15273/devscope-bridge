/**
 * Parse intercepted LinkedIn API JSON into profile/search fragments.
 */
(function () {
  'use strict';

  const CORE = typeof window !== 'undefined' ? window.__htLinkedInPeopleSearchCore : null;

  function safeGet(obj, path) {
    return path.split('.').reduce((acc, key) => (acc && acc[key] != null ? acc[key] : null), obj);
  }

  function parseVoyagerDashProfile(body) {
    if (!body) return null;
    const included = body.included || body.data?.included || [];
    const profile = included.find((x) =>
      String(x?.$type || '').includes('Profile') || x?.firstName,
    );
    if (!profile) return null;
    const first = profile.firstName || '';
    const last = profile.lastName || '';
    return {
      full_name: `${first} ${last}`.trim(),
      headline: profile.headline || profile.occupation || '',
      location: profile.geoLocationName || profile.locationName || '',
      publicIdentifier: profile.publicIdentifier || null,
      scraped_via: 'api',
    };
  }

  function parseEntityResultViewModels(body, scrapedVia) {
    if (CORE?.parseEntityResultViewModels) {
      return CORE.parseEntityResultViewModels(body, scrapedVia);
    }
    return [];
  }

  function parseVoyagerPeopleSearch(body, scrapedVia) {
    if (CORE?.parseVoyagerPeopleSearch) {
      return CORE.parseVoyagerPeopleSearch(body, scrapedVia || 'api');
    }
    return parseEntityResultViewModels(body, scrapedVia || 'api');
  }

  function parseSalesPeopleSearch(body) {
    const elements = body?.elements || body?.data?.elements || [];
    return elements.map((el) => ({
      name: el.fullName || el.name || '',
      headline: el.headline || '',
      sales_profile_url: el.entityUrn
        ? `https://www.linkedin.com/sales/people/${encodeURIComponent(el.entityUrn)}`
        : '',
      scraped_via: 'api',
    }));
  }

  function parseSalesProfile(body) {
    const el = body?.elements?.[0] || body?.data || body;
    if (!el) return null;
    return {
      full_name: el.fullName || el.name || '',
      headline: el.headline || '',
      location: el.location || el.geoRegion || '',
      scraped_via: 'api',
    };
  }

  function parseTalentSearchHits(body) {
    const hits = body?.elements || body?.data?.elements || body?.results || [];
    return hits.map((hit) => ({
      name: hit.fullName || hit.name || '',
      headline: hit.headline || '',
      page_url: hit.profileUrl || hit.linkedInProfileUrl || '',
      scraped_via: 'api',
    }));
  }

  function parseTalentProfile(body) {
    const el = body?.elements?.[0] || body?.data || body;
    if (!el) return null;
    return {
      full_name: el.fullName || el.name || '',
      headline: el.headline || '',
      location: el.location || '',
      public_linkedin_url: el.publicProfileUrl || el.linkedInProfileUrl || '',
      scraped_via: 'api',
    };
  }

  function parseTalentHiringCandidates(body) {
    const list = body?.elements || body?.data?.elements || [];
    return list.map((c) => ({
      name: c.fullName || c.name || '',
      page_url: c.profileUrl || '',
      scraped_via: 'api',
    }));
  }

  function parsePublicSearchRoute(routeKey, body) {
    const via = routeKey === 'flagship_rsc_action' ? 'page_json' : 'api';
    return parseVoyagerPeopleSearch(body, via);
  }

  function parseFromCache(routeKey) {
    const intercept = window.__htLinkedInIntercept;
    const entry = intercept?.getLatest(routeKey);
    if (!entry?.body) return null;
    switch (routeKey) {
      case 'voyager_dash_profile':
        return parseVoyagerDashProfile(entry.body);
      case 'voyager_search_clusters':
      case 'voyager_graphql_search':
      case 'flagship_rsc_action':
        return parsePublicSearchRoute(routeKey, entry.body);
      case 'sales_people_search':
        return parseSalesPeopleSearch(entry.body);
      case 'sales_profile':
        return parseSalesProfile(entry.body);
      case 'talent_search_hits':
        return parseTalentSearchHits(entry.body);
      case 'talent_profile':
        return parseTalentProfile(entry.body);
      case 'talent_hiring':
        return parseTalentHiringCandidates(entry.body);
      default:
        return null;
    }
  }

  function parseAllFromCache(routeKeys) {
    const intercept = window.__htLinkedInIntercept;
    if (!intercept?.getAll) return [];
    const keys = Array.isArray(routeKeys) ? routeKeys : [routeKeys];
    const cards = [];
    const seen = new Set();
    for (const routeKey of keys) {
      for (const entry of intercept.getAll(routeKey)) {
        const hits = parsePublicSearchRoute(routeKey, entry.body);
        for (const hit of hits || []) {
          const slug = hit.publicIdentifier || hit.linkedin_url;
          if (!slug || seen.has(slug)) continue;
          seen.add(slug);
          cards.push(hit);
        }
      }
    }
    return cards;
  }

  window.__htLinkedInApiParsers = {
    parseVoyagerDashProfile,
    parseEntityResultViewModels,
    parseVoyagerPeopleSearch,
    parseSalesPeopleSearch,
    parseSalesProfile,
    parseTalentSearchHits,
    parseTalentProfile,
    parseTalentHiringCandidates,
    parseFromCache,
    parseAllFromCache,
  };
})();
