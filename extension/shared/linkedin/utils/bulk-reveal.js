/**
 * Scroll virtualized LinkedIn lists to reveal lazy-loaded rows (Lusha pattern).
 */
(function () {
  'use strict';

  async function revealPendingRows(rowSelectors, childSelectors, opts = {}) {
    const query = window.__htLinkedInQuery;
    const delay = window.__htLinkedInText?.delay || ((ms) => new Promise((r) => setTimeout(r, ms)));
    const maxPasses = opts.maxPasses || 8;
    const scrollStep = opts.scrollStep || Math.floor(window.innerHeight * 0.7) || 500;

    const rowsList = Array.isArray(rowSelectors) ? rowSelectors : [rowSelectors];
    const childList = Array.isArray(childSelectors) ? childSelectors : [childSelectors];

    let scrollY = 0;
    const maxScroll = Math.max(document.body.scrollHeight, document.documentElement.scrollHeight);

    for (let pass = 0; pass < maxPasses; pass++) {
      const { elements: rows } = query.queryAllFirst(rowsList);
      if (!rows.length) {
        scrollY += scrollStep;
        window.scrollTo(0, Math.min(scrollY, maxScroll));
        await delay(400);
        continue;
      }

      let revealed = 0;
      for (const row of rows.slice(0, 50)) {
        row.scrollIntoView({ block: 'center', behavior: 'instant' });
        await delay(120);
        const { element: child } = query.queryFirst(childList, row);
        if (child) revealed += 1;
      }

      if (revealed >= rows.length * 0.8) break;
      scrollY += scrollStep;
      window.scrollTo(0, Math.min(scrollY, maxScroll));
      await delay(350);
    }

    window.scrollTo(0, 0);
    await delay(300);
  }

  function observeVisibleRows(rowSelectors, onBatch, opts = {}) {
    const query = window.__htLinkedInQuery;
    const seen = new Set();
    const threshold = opts.threshold ?? 0.5;

    const observer = new IntersectionObserver(
      (entries) => {
        const batch = [];
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          const key = entry.target.getAttribute('data-ht-row-id') || entry.target.innerText?.slice(0, 40);
          if (!key || seen.has(key)) continue;
          seen.add(key);
          batch.push(entry.target);
        }
        if (batch.length) onBatch(batch);
      },
      { threshold },
    );

    const { elements } = query.queryAllFirst(rowSelectors);
    elements.forEach((el, i) => {
      if (!el.getAttribute('data-ht-row-id')) el.setAttribute('data-ht-row-id', `row-${i}`);
      observer.observe(el);
    });

    return () => observer.disconnect();
  }

  window.__htLinkedInBulkReveal = {
    revealPendingRows,
    observeVisibleRows,
  };
})();
