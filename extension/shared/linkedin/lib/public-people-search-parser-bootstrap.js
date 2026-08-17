/**
 * Browser bootstrap for public-people-search-parser-core (IIFE consumers).
 */
(function () {
  'use strict';

  function stripQueryFromUrl(url) {
    if (!url) return '';
    return String(url).split('?')[0];
  }

  function slugFromLinkedInUrl(url) {
    const m = String(url || '').match(/\/in\/([^/?#]+)/);
    return m ? m[1] : '';
  }

  function extractPhotoFromEntity(item) {
    const segment =
      item?.image?.attributes?.[0]?.detailData?.nonEntityProfilePicture?.vectorImage
        ?.artifacts?.[0]?.fileIdentifyingUrlPathSegment;
    if (!segment) return '';
    if (String(segment).startsWith('http')) return segment;
    return `https://media.licdn.com/dms/image/${segment}`;
  }

  function isEntityResultViewModel(entry) {
    if (!entry?.$type) return false;
    const typeName = String(entry.$type).split('.').pop();
    if (typeName !== 'EntityResultViewModel') return false;
    if (entry.template && entry.template !== 'UNIVERSAL') return false;
    const trackingId = entry?.trackingUrn?.split(':')?.[3];
    if (trackingId === 'headless') return false;
    return true;
  }

  function parseEntityResultViewModels(body, scrapedVia) {
    const included = body?.included;
    if (!Array.isArray(included)) return [];
    const via = scrapedVia || 'page_json';
    const text = window.__htLinkedInText;

    return included
      .filter(isEntityResultViewModel)
      .map((item) => {
        const rawUrl = stripQueryFromUrl(item.navigationUrl || '');
        const linkedin_url = text?.normalizePublicProfileUrl(rawUrl) || rawUrl;
        const slug = text?.slugFromUrl(linkedin_url) || slugFromLinkedInUrl(linkedin_url);
        return {
          name: item?.title?.text || '',
          headline: item?.primarySubtitle?.text || '',
          location: item?.secondarySubtitle?.text || '',
          linkedin_url,
          publicIdentifier: slug,
          photo_url: extractPhotoFromEntity(item) || undefined,
          result_urn: item.trackingUrn || item.entityUrn || undefined,
          scraped_via: via,
          surface: 'public_people_search',
          page_url: linkedin_url,
        };
      })
      .filter((card) => card.linkedin_url && card.publicIdentifier);
  }

  function parseVoyagerPeopleSearch(body, scrapedVia) {
    if (!body) return [];
    if (Array.isArray(body.included)) {
      return parseEntityResultViewModels(body, scrapedVia);
    }
    if (body.data && Array.isArray(body.data.included)) {
      return parseEntityResultViewModels({ included: body.data.included }, scrapedVia);
    }
    return [];
  }

  function cardRichnessScore(card) {
    let score = 0;
    if (card.name) score += 2;
    if (card.headline) score += 2;
    if (card.location) score += 1;
    if (card.photo_url) score += 1;
    if (card.connection_degree) score += 1;
    if (card.mutual_connections) score += 1;
    return score;
  }

  function mergeSearchCardsBySlug(cards) {
    const bySlug = new Map();
    for (const card of cards) {
      const slug =
        card.publicIdentifier ||
        window.__htLinkedInText?.slugFromUrl(card.linkedin_url) ||
        slugFromLinkedInUrl(card.linkedin_url);
      if (!slug) continue;
      const existing = bySlug.get(slug);
      if (!existing || cardRichnessScore(card) > cardRichnessScore(existing)) {
        bySlug.set(slug, { ...existing, ...card, publicIdentifier: slug });
      }
    }
    return [...bySlug.values()];
  }

  function countScrapeSources(cards) {
    const counts = { page_json: 0, api: 0, dom: 0, mixed: 0 };
    for (const card of cards || []) {
      const via = card.scraped_via || 'dom';
      if (counts[via] != null) counts[via] += 1;
      else counts.dom += 1;
    }
    return counts;
  }

  window.__htLinkedInPeopleSearchCore = {
    parseEntityResultViewModels,
    parseVoyagerPeopleSearch,
    mergeSearchCardsBySlug,
    cardRichnessScore,
    countScrapeSources,
  };
})();
