/**
 * Extract embedded LinkedIn page JSON (SDUI / bpr-guid code blocks).
 */
(function () {
  'use strict';

  function safeParseJson(text) {
    if (!text) return null;
    try {
      return typeof text === 'string' ? JSON.parse(text) : text;
    } catch (_) {
      return null;
    }
  }

  function extractLatestPageJson(doc) {
    const root = doc || (typeof document !== 'undefined' ? document : null);
    if (!root?.querySelectorAll) return null;
    const codes = root.querySelectorAll("code[id^='bpr-guid-']");
    if (!codes.length) return null;
    return safeParseJson(codes[codes.length - 1].textContent);
  }

  function extractAllPageJsonBlocks(doc) {
    const root = doc || (typeof document !== 'undefined' ? document : null);
    if (!root?.querySelectorAll) return null;
    const codes = root.querySelectorAll("code[id^='bpr-guid-']");
    const blocks = [];
    const mergedIncluded = [];
    for (const code of codes) {
      const parsed = safeParseJson(code.textContent);
      if (!parsed) continue;
      blocks.push(parsed);
      if (Array.isArray(parsed.included)) mergedIncluded.push(...parsed.included);
    }
    if (!blocks.length) return null;
    return {
      blocks,
      included: mergedIncluded,
      latest: blocks[blocks.length - 1],
    };
  }

  window.__htLinkedInPageJson = {
    safeParseJson,
    extractLatestPageJson,
    extractAllPageJsonBlocks,
  };
})();
