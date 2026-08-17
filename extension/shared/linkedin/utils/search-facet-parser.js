/**
 * Parse LinkedIn People search URL facets (geoUrn, facetNetwork, etc.).
 */
(function () {
  'use strict';

  const FACET_KEY_LABELS = {
    geoUrn: 'location',
    facetGeoRegion: 'region',
    facetNetwork: 'network',
    facetConnectionOf: 'connections_of',
    facetCurrentCompany: 'current_company',
    facetPastCompany: 'past_company',
    facetSchool: 'school',
    facetIndustry: 'industry',
    facetProfileLanguage: 'language',
    facetServiceCategory: 'service',
    facetSkill: 'skill',
    facetSeniority: 'seniority',
    origin: 'origin',
    keywords: 'keywords',
    sid: 'session_id',
  };

  const NETWORK_CODE_LABELS = { F: '1st', S: '2nd', O: '3rd+' };

  function tryParseJson(value) {
    if (value == null || value === '') return null;
    try {
      return JSON.parse(value);
    } catch (_) {
      return value;
    }
  }

  function flattenFacetValue(key, parsed) {
    if (parsed == null) return [];
    if (Array.isArray(parsed)) {
      if (key === 'facetNetwork') {
        return parsed.map((c) => NETWORK_CODE_LABELS[c] || c);
      }
      return parsed.map(String);
    }
    return [String(parsed)];
  }

  function parseSearchUrlFacets(url) {
    const href = String(url || (typeof location !== 'undefined' ? location.href : ''));
    let params;
    try {
      params = new URL(href).searchParams;
    } catch (_) {
      return { raw: {}, facets: [], keywords: '', origin: null };
    }

    const raw = {};
    const facets = [];

    for (const [key, value] of params.entries()) {
      if (
        key.startsWith('facet') ||
        key === 'geoUrn' ||
        key === 'origin' ||
        key === 'keywords' ||
        key === 'sid'
      ) {
        raw[key] = value;
        const parsed = tryParseJson(value);
        const label = FACET_KEY_LABELS[key] || key;
        const values = flattenFacetValue(key, parsed);
        if (values.length) {
          facets.push({ key, label, values, raw: value });
        } else if (key === 'keywords' || key === 'origin') {
          facets.push({ key, label, values: [String(parsed ?? value)], raw: value });
        }
      }
    }

    return {
      raw,
      facets,
      keywords: params.get('keywords') || '',
      origin: params.get('origin'),
    };
  }

  function facetsToSummary(facets) {
    return (facets || [])
      .filter((f) => f.key !== 'sid' && f.key !== 'origin')
      .map((f) => `${f.label}: ${f.values.join(', ')}`)
      .join(' · ');
  }

  window.__htLinkedInFacetParser = {
    parseSearchUrlFacets,
    facetsToSummary,
    FACET_KEY_LABELS,
    NETWORK_CODE_LABELS,
  };
})();
