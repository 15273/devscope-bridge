/**
 * LinkedIn API intercept — XHR + fetch at document_start (ContactOut pattern).
 * Caches responses locally; no external backend calls.
 */
(function () {
  'use strict';

  const CACHE_MAX = 50;
  const ROUTES = [
    { key: 'voyager_dash_profile', match: 'voyager/api/identity/dash/profiles' },
    { key: 'voyager_search_clusters', match: 'voyager/api/search/dash/clusters' },
    {
      key: 'voyager_graphql_search',
      match: 'voyager/api/graphql',
      alsoMatch: 'voyagerSearchDashClusters',
    },
    { key: 'flagship_rsc_action', match: 'flagship-web/rsc-action' },
    { key: 'sales_people_search', match: 'sales-api/salesApiPeopleSearch' },
    { key: 'sales_profile', match: 'sales-api/salesApiProfiles' },
    { key: 'talent_search_hits', match: 'talent/search/api/talentRecruiterSearchHits' },
    { key: 'talent_profile', match: 'talent/api/talentProfiles' },
    { key: 'talent_hiring', match: 'talent/api/talentHiringCandidates' },
    { key: 'talent_graphql', match: 'talent/api/graphql' },
  ];

  const cache = [];
  window.__htLinkedInApiCache = cache;

  function classifyUrl(url) {
    const u = String(url || '');
    for (const route of ROUTES) {
      if (!u.includes(route.match)) continue;
      if (route.alsoMatch && !u.includes(route.alsoMatch)) continue;
      return route.key;
    }
    return null;
  }

  function pushCache(entry) {
    cache.push(entry);
    while (cache.length > CACHE_MAX) cache.shift();
    try {
      window.dispatchEvent(
        new CustomEvent('htLinkedInApiResponse', { detail: entry }),
      );
    } catch (_) {
      /* isolated world */
    }
  }

  function parseResponseBody(xhr) {
    try {
      const text = xhr.responseText || xhr.response;
      if (!text) return null;
      return typeof text === 'string' ? JSON.parse(text) : text;
    } catch (_) {
      return null;
    }
  }

  function patchXHR() {
    const origOpen = XMLHttpRequest.prototype.open;
    const origSend = XMLHttpRequest.prototype.send;

    XMLHttpRequest.prototype.open = function patchedOpen(method, url, ...rest) {
      this.__htUrl = url;
      this.__htMethod = method;
      return origOpen.call(this, method, url, ...rest);
    };

    XMLHttpRequest.prototype.send = function patchedSend(body) {
      this.addEventListener('load', function onLoad() {
        const routeKey = classifyUrl(this.__htUrl);
        if (!routeKey || this.status < 200 || this.status >= 300) return;
        const parsed = parseResponseBody(this);
        if (parsed) {
          pushCache({
            routeKey,
            url: this.__htUrl,
            method: this.__htMethod,
            body: parsed,
            at: Date.now(),
          });
        }
      });
      return origSend.call(this, body);
    };
  }

  function patchFetch() {
    const origFetch = window.fetch;
    if (!origFetch) return;

    window.fetch = async function patchedFetch(input, init) {
      const url = typeof input === 'string' ? input : input?.url || '';
      const response = await origFetch.call(this, input, init);
      const routeKey = classifyUrl(url);
      if (routeKey && response.ok) {
        try {
          const clone = response.clone();
          const body = await clone.json();
          pushCache({
            routeKey,
            url,
            method: (init?.method || 'GET').toUpperCase(),
            body,
            at: Date.now(),
          });
        } catch (_) {
          /* non-json */
        }
      }
      return response;
    };
  }

  function getLatest(routeKey) {
    for (let i = cache.length - 1; i >= 0; i--) {
      if (cache[i].routeKey === routeKey) return cache[i];
    }
    return null;
  }

  function getAll(routeKey) {
    return cache.filter((e) => e.routeKey === routeKey);
  }

  patchXHR();
  patchFetch();

  window.__htLinkedInIntercept = {
    classifyUrl,
    getLatest,
    getAll,
    ROUTES,
  };
})();
