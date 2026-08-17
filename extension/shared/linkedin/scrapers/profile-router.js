/**
 * Profile scrape router — dispatches by detected LinkedIn surface.
 */
(function () {
  'use strict';

  async function scrapeCurrentProfile(opts = {}) {
    const router = window.__htLinkedInRouter;
    const normalizer = window.__htLinkedInNormalizer;
    const surface = router.detectLinkedInSurface(location.href);

    let raw = null;
    let selectorHits = {};

    switch (surface.id) {
      case 'public_profile': {
        const pub = window.__htLinkedInPublicProfile;
        await pub.preparePage({ initialWait: opts.initialWait || 2500, extraWait: opts.extraWait });
        raw = opts.full ? await pub.extractProfileFull() : pub.extractProfile();
        if (pub.isProfileEmpty(raw) && !opts._retried) {
          await pub.preparePage({ initialWait: 2500, extraWait: 1500 });
          raw = opts.full ? await pub.extractProfileFull() : pub.extractProfile();
        }
        break;
      }
      case 'talent_profile': {
        raw = await window.__htLinkedInTalentProfile.scrapeTalentProfileAsync();
        selectorHits = raw.selector_hits || {};
        if (raw.public_linkedin_url && opts.full && window.__htLinkedInPublicProfile) {
          // Optional: deep enrich via public URL iframe chain if user navigates — skip auto-nav
        }
        break;
      }
      case 'recruiter_lite_profile': {
        raw = await window.__htLinkedInRecruiterLiteProfile.scrapeRecruiterLiteProfile();
        selectorHits = raw.selector_hits || {};
        break;
      }
      case 'sales_profile': {
        raw = await window.__htLinkedInSalesProfile.scrapeSalesProfileAsync();
        selectorHits = raw.selector_hits || {};
        break;
      }
      default:
        throw new Error(`Unsupported profile surface: ${surface.id}`);
    }

    return normalizer.normalizeProfile(raw, surface, selectorHits);
  }

  function isProfileEmpty(data) {
    if (window.__htLinkedInPublicProfile?.isProfileEmpty?.(data)) {
      return window.__htLinkedInPublicProfile.isProfileEmpty(data);
    }
    return !data?.full_name && !(data?.raw_text?.length > 80);
  }

  window.__htLinkedInProfileRouter = {
    scrapeCurrentProfile,
    isProfileEmpty,
  };
})();
