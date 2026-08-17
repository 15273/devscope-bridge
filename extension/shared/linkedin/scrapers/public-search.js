/**
 * Public people search scraper — page JSON + API cache + DOM fallback.
 */
(function () {
  'use strict';

  const SURFACE = { id: 'public_people_search' };
  const API_ROUTE_KEYS = [
    'voyager_graphql_search',
    'voyager_search_clusters',
    'flagship_rsc_action',
  ];

  const cardApi = () => window.__htLinkedInSearchCardExtractor;
  const textApi = () => window.__htLinkedInText;
  const coreApi = () => window.__htLinkedInPeopleSearchCore;
  const parsersApi = () => window.__htLinkedInApiParsers;
  const pageJsonApi = () => window.__htLinkedInPageJson;
  const normalizerApi = () => window.__htLinkedInNormalizer;

  function sleep(ms) {
    return textApi()?.delay(ms) ?? new Promise((r) => setTimeout(r, ms));
  }

  function slugForCard(card) {
    return (
      card.publicIdentifier ||
      textApi()?.slugFromUrl(card.linkedin_url || card.page_url || '') ||
      ''
    );
  }

  function toNormalizedCard(raw) {
    const card = normalizerApi()?.normalizeSearchCard(raw, SURFACE) || raw;
    if (raw.scraped_via) card.scraped_via = raw.scraped_via;
    return card;
  }

  function collectFromPageJsonRaw() {
    const pageJson = pageJsonApi();
    const core = coreApi();
    if (!pageJson?.extractAllPageJsonBlocks || !core?.parseVoyagerPeopleSearch) return [];

    const bundle = pageJson.extractAllPageJsonBlocks();
    if (!bundle) return [];

    const body = bundle.included?.length
      ? { included: bundle.included }
      : bundle.latest;
    return core.parseVoyagerPeopleSearch(body, 'page_json');
  }

  function collectFromApiCacheRaw() {
    const parsers = parsersApi();
    if (!parsers?.parseAllFromCache) return [];
    return parsers.parseAllFromCache(API_ROUTE_KEYS);
  }

  function scrapeVisibleCardsDomRaw(seen, maxNew, skipSlugs) {
    const profiles = [];
    const extract = cardApi()?.extractCardFromAnchor;
    if (!extract) return profiles;

    const rowSelectors = [
      'main [role="listitem"]',
      '[data-chameleon-result-urn]',
      '.reusable-search__result-container',
    ];
    let rows = [];
    for (const sel of rowSelectors) {
      rows = [...document.querySelectorAll(sel)];
      if (rows.length) break;
    }

    const pushCard = (card) => {
      if (!card) return;
      card.scraped_via = card.scraped_via || 'dom';
      const slug = slugForCard(card);
      if (!slug || seen.has(slug) || skipSlugs?.has(slug)) return;
      seen.add(slug);
      profiles.push(card);
    };

    if (rows.length) {
      for (const row of rows) {
        if (profiles.length >= maxNew) break;
        const anchor = row.querySelector('a[href*="/in/"]');
        pushCard(extract(anchor, seen));
      }
      return profiles;
    }

    const root =
      document.querySelector('main') ||
      document.querySelector('.search-results-container') ||
      document.body;
    for (const anchor of root.querySelectorAll('a[href*="/in/"]')) {
      if (profiles.length >= maxNew) break;
      pushCard(extract(anchor, seen));
    }
    return profiles;
  }

  function mergeAllTierRawCards() {
    const core = coreApi();
    let raw = [...collectFromPageJsonRaw(), ...collectFromApiCacheRaw()];
    const skipSlugs = new Set(raw.map(slugForCard).filter(Boolean));
    const domRaw = scrapeVisibleCardsDomRaw(new Set(), 999, skipSlugs);
    if (core?.mergeSearchCardsBySlug) {
      return core.mergeSearchCardsBySlug([...raw, ...domRaw]);
    }
    return [...raw, ...domRaw];
  }

  function scrapeVisibleCardsDom(seen, maxNew, skipSlugs) {
    return scrapeVisibleCardsDomRaw(seen, maxNew, skipSlugs).map(toNormalizedCard);
  }

  function scrapeVisibleCards(seenInput, maxNew) {
    const seen = seenInput instanceof Set ? seenInput : new Set();
    const limit = Math.max(maxNew || 25, 1);
    const out = [];
    for (const card of mergeAllTierRawCards()) {
      const slug = slugForCard(card);
      if (!slug || seen.has(slug)) continue;
      seen.add(slug);
      out.push(toNormalizedCard(card));
      if (out.length >= limit) break;
    }
    return out;
  }

  function collectFromPageJson(seen, maxNew) {
    const out = [];
    for (const card of collectFromPageJsonRaw()) {
      const slug = slugForCard(card);
      if (!slug || seen.has(slug)) continue;
      seen.add(slug);
      out.push(toNormalizedCard(card));
      if (out.length >= maxNew) break;
    }
    return out;
  }

  function collectFromApiCache(seen, maxNew) {
    const out = [];
    for (const card of collectFromApiCacheRaw()) {
      const slug = slugForCard(card);
      if (!slug || seen.has(slug)) continue;
      seen.add(slug);
      out.push(toNormalizedCard(card));
      if (out.length >= maxNew) break;
    }
    return out;
  }

  function countTierHits() {
    const pageJson = pageJsonApi();
    const parsers = parsersApi();
    const core = coreApi();
    let pageJsonHits = 0;
    let apiHits = 0;

    const bundle = pageJson?.extractAllPageJsonBlocks?.();
    if (bundle && core?.parseVoyagerPeopleSearch) {
      const body = bundle.included?.length
        ? { included: bundle.included }
        : bundle.latest;
      pageJsonHits = core.parseVoyagerPeopleSearch(body, 'page_json').length;
    }
    if (parsers?.parseAllFromCache) {
      apiHits = parsers.parseAllFromCache(API_ROUTE_KEYS).length;
    }

    return { page_json: pageJsonHits, api: apiHits };
  }

  function currentPageMarker() {
    const active = document.querySelector(
      'li.artdeco-pagination__indicator--number.active button, button[aria-current="page"]',
    );
    if (active) return (active.textContent || '').trim();
    const m = location.search.match(/[?&]page=(\d+)/);
    return m ? m[1] : '1';
  }

  function findNextPageControl() {
    const registry = window.__htLinkedInRegistry;
    const { element } = window.__htLinkedInQuery.queryFirst(
      registry?.SELECTORS?.public_people_search?.next_page || [],
    );
    return element;
  }

  async function scrollCurrentPage() {
    const step = Math.floor(window.innerHeight * 0.75) || 500;
    let pos = 0;
    const maxScroll = document.body.scrollHeight;
    while (pos < maxScroll) {
      window.scrollTo(0, pos);
      pos += step;
      await sleep(350);
    }
    window.scrollTo(0, 0);
    await sleep(400);
  }

  async function waitForPageChange(previousMarker, timeoutMs = 12000) {
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
      await sleep(400);
      if (currentPageMarker() !== previousMarker) return true;
    }
    return currentPageMarker() !== previousMarker;
  }

  async function goToNextPage() {
    const control = findNextPageControl();
    if (!control) return false;
    const before = currentPageMarker();
    control.scrollIntoView({ block: 'center' });
    await sleep(300);
    control.click();
    if (await waitForPageChange(before)) {
      await sleep(1800);
      return true;
    }
    return false;
  }

  function hasEmptyResultsMessage() {
    const main = document.querySelector('main');
    const text = (main?.innerText || '').slice(0, 4000);
    return /no results found|לא נמצאו תוצאות/i.test(text);
  }

  async function deepScrapeSearch(maxProfiles, maxPages) {
    if (hasEmptyResultsMessage()) return [];
    const seen = new Set();
    const profiles = [];
    const pageLimit = Math.min(Math.max(maxPages || 12, 1), 20);
    const target = Math.min(maxProfiles || 120, 150);

    for (let page = 0; page < pageLimit && profiles.length < target; page++) {
      await scrollCurrentPage();
      const batch = scrapeVisibleCards(seen, target - profiles.length);
      profiles.push(...batch);
      if (profiles.length >= target) break;
      if (!findNextPageControl()) break;
      if (!(await goToNextPage())) break;
    }
    return profiles;
  }

  function readSearchPageState() {
    const tierHits = countTierHits();
    const domSample = scrapeVisibleCardsDomRaw(new Set(), 999);
    if (window.__htLinkedInSearchState?.readSearchPageState) {
      return {
        ...window.__htLinkedInSearchState.readSearchPageState(),
        page_json_hits: tierHits.page_json,
        api_cache_hits: tierHits.api,
        dom_hits: domSample.length,
      };
    }
    return {
      page_url: location.href,
      keywords: new URLSearchParams(location.search).get('keywords') || '',
      surface: 'public_people_search',
      visible_cards: scrapeVisibleCards(new Set(), 999).length,
      page: currentPageMarker(),
      page_json_hits: tierHits.page_json,
      api_cache_hits: tierHits.api,
      dom_hits: domSample.length,
    };
  }

  window.__htLinkedInPublicSearch = {
    scrapeVisibleCards,
    scrapeVisibleCardsDom,
    collectFromPageJson,
    collectFromApiCache,
    deepScrapeSearch,
    readSearchPageState,
    hasEmptyResultsMessage,
    countTierHits,
  };
})();
