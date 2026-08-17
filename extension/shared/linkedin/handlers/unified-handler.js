/**
 * Unified Chrome message handler for LinkedIn scrape operations.
 */
(function () {
  'use strict';

  if (window.__htLinkedInUnifiedHandlerInstalled) return;
  window.__htLinkedInUnifiedHandlerInstalled = true;

  const FLAG_KEY = 'ht_linkedin_surface_v2_enabled';

  async function isV2Enabled() {
    try {
      const stored = await chrome.storage.local.get(FLAG_KEY);
      if (stored[FLAG_KEY] === undefined) return true;
      return Boolean(stored[FLAG_KEY]);
    } catch (_) {
      return true;
    }
  }

  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg.type === 'SCRAPE_LINKEDIN_PROFILE') {
      (async () => {
        try {
          const v2 = await isV2Enabled();
          const router = window.__htLinkedInProfileRouter;
          const legacy = window.__htLinkedInScraper;

          if (v2 && router) {
            const data = await router.scrapeCurrentProfile({
              full: Boolean(msg.full),
              initialWait: msg.initialWait,
            });
            sendResponse({ success: true, data });
            return;
          }

          if (legacy) {
            await legacy.preparePage({ initialWait: msg.initialWait || 2500 });
            let data = legacy.extractProfileFull ? await legacy.extractProfileFull() : legacy.extractProfile();
            if (legacy.isProfileEmpty?.(data)) {
              await legacy.preparePage({ initialWait: 2500, extraWait: 1500 });
              data = legacy.extractProfileFull ? await legacy.extractProfileFull() : legacy.extractProfile();
            }
            sendResponse({ success: true, data });
            return;
          }

          sendResponse({ success: false, error: 'No profile scraper loaded' });
        } catch (e) {
          sendResponse({ success: false, error: String(e) });
        }
      })();
      return true;
    }

    if (msg.type === 'SCRAPE_LINKEDIN_SEARCH') {
      (async () => {
        try {
          const result = await window.__htLinkedInSearchRouter.scrapeSearch({ deep: false });
          sendResponse({ success: true, data: result });
        } catch (e) {
          sendResponse({ success: false, error: String(e) });
        }
      })();
      return true;
    }

    if (msg.type === 'READ_LINKEDIN_SEARCH_STATE') {
      try {
        sendResponse({ success: true, data: window.__htLinkedInSearchRouter.readSearchState() });
      } catch (e) {
        sendResponse({ success: false, error: String(e) });
      }
      return true;
    }

    if (msg.type === 'SCRAPE_LINKEDIN_SEARCH_DEEP') {
      (async () => {
        try {
          const result = await window.__htLinkedInSearchRouter.scrapeSearch({
            deep: true,
            maxProfiles: msg.maxProfiles,
            maxPages: msg.maxPages,
          });
          const empty = window.__htLinkedInPublicSearch?.hasEmptyResultsMessage?.();
          sendResponse({
            success: true,
            data: { ...result, empty_results: empty && !(result.profiles || []).length },
          });
        } catch (e) {
          sendResponse({ success: false, error: String(e) });
        }
      })();
      return true;
    }

    if (msg.type === 'PROBE_LINKEDIN_SELECTORS') {
      try {
        const report = window.__htLinkedInSelectorProbe?.probe?.() || {};
        sendResponse({ success: true, data: report });
      } catch (e) {
        sendResponse({ success: false, error: String(e) });
      }
      return true;
    }

    if (msg.type === 'GET_LINKEDIN_SURFACE') {
      try {
        const surface = window.__htLinkedInRouter.detectLinkedInSurface(location.href);
        sendResponse({ success: true, data: surface });
      } catch (e) {
        sendResponse({ success: false, error: String(e) });
      }
      return true;
    }
  });
})();
