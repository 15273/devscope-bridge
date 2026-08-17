/**
 * Enhanced search result card extraction (public people search).
 */
(function () {
  'use strict';

  const NOISE_RE =
    /^(view profile|connect|message|follow|send inmail|promoted|premium|open to work|hiring|actively hiring|\d+|•|·|1st|2nd|3rd|[+\-]?\d+ mutual connection)$/i;

  function extractTextLines(containerEl) {
    if (!containerEl) return [];
    return (containerEl.innerText || '')
      .split('\n')
      .map((l) => l.trim())
      .filter((l) => l.length > 0 && !NOISE_RE.test(l));
  }

  function looksLikeLocation(str) {
    if (!str || str.length > 50 || str.includes('·')) return false;
    return /[A-Za-z\u0590-\u05FF]/.test(str) && str.split(/\s+/).length <= 6;
  }

  function parseNameLine(line) {
    const clean = window.__htLinkedInText?.cleanLine?.(line) || line;
    const parts = (clean || '').split('·').map((s) => s.trim()).filter(Boolean);
    let name = parts[0] || '';
    let connection_degree = '';
    const degreePatterns = [
      /^(1st|2nd|3rd|3rd\+)$/i,
      /^(ראשון|שני|שלישי)$/,
    ];
    const degreeMap = { ראשון: '1st', שני: '2nd', שלישי: '3rd' };
    for (const part of parts.slice(1)) {
      if (/^(1st|2nd|3rd|3rd\+)$/i.test(part)) connection_degree = part;
      if (degreeMap[part]) connection_degree = degreeMap[part];
    }
    if (!connection_degree) {
      const m = (clean || '').match(/(?:•|\u00b7)\s*(1st|2nd|3rd\+?|ראשון|שני|שלישי)/i);
      if (m) {
        connection_degree = degreeMap[m[1]] || m[1];
      }
    }
    if (name.includes('/')) name = '';
    return { name: window.__htLinkedInText?.cleanLine?.(name) || name, connection_degree };
  }

  function readStructuredFields(container) {
    const query = window.__htLinkedInQuery;
    const fields = {};

    fields.title = query?.textFromFirst?.(
      ['.entity-result__title-text', '.entity-result__title-line', 'span[dir="ltr"] span[aria-hidden="true"]'],
      container,
    );
    fields.subtitle = query?.textFromFirst?.(
      ['.entity-result__primary-subtitle', '.entity-result__summary'],
      container,
    );
    fields.secondary = query?.textFromFirst?.(
      ['.entity-result__secondary-subtitle'],
      container,
    );

    const urn = container.getAttribute?.('data-chameleon-result-urn') ||
      container.closest('[data-chameleon-result-urn]')?.getAttribute('data-chameleon-result-urn');
    if (urn) fields.result_urn = urn;

    return fields;
  }

  function extractCardFromAnchor(anchor, seen) {
    const text = window.__htLinkedInText;
    const normalized = text?.normalizePublicProfileUrl(anchor.href);
    if (!normalized) return null;

    const slug = text?.slugFromUrl(normalized);
    if (!slug || seen.has(slug)) return null;
    seen.add(slug);

    let container = anchor;
    for (let i = 0; i < 10; i++) {
      if (!container.parentElement) break;
      container = container.parentElement;
      if (
        container.tagName === 'LI' ||
        container.getAttribute('data-chameleon-result-urn') ||
        container.getAttribute('role') === 'listitem'
      ) {
        break;
      }
    }

    const structured = readStructuredFields(container);
    const lines = extractTextLines(container);
    const parsed = parseNameLine(lines[0] || structured.title || '');

    let headline = structured.subtitle || '';
    let location = structured.secondary || '';
    let current_company = '';
    let mutual_connections = '';
    let open_to_work = false;
    let is_hiring = false;

    for (let i = 1; i < lines.length; i++) {
      const line = lines[i];
      if (!headline && line.length > 8 && !looksLikeLocation(line) && !/mutual|משותפ/i.test(line)) {
        headline = line;
        continue;
      }
      if (!location && looksLikeLocation(line)) {
        location = line;
        continue;
      }
      if (!mutual_connections && /mutual|משותפ/i.test(line)) {
        mutual_connections = line;
        continue;
      }
      if (!current_company && /(current|נוכחי| at | @ |ב-|ב\s)/i.test(line)) {
        current_company = line;
      }
      if (/open to work|פנוי/i.test(line)) open_to_work = true;
      if (/actively hiring|מגייס/i.test(line)) is_hiring = true;
    }

    let photo_url = '';
    const photoEl = container.querySelector(
      'img[src*="licdn.com"], img.presence-entity__image, img.EntityPhoto-circle-3',
    );
    if (
      photoEl?.src &&
      !photoEl.src.includes('data:') &&
      !/ghost|default|placeholder/i.test(photoEl.src)
    ) {
      photo_url = photoEl.src;
    }

    const name = parsed.name || structured.title || anchor.textContent?.trim() || '';

    return {
      linkedin_url: normalized,
      name,
      headline,
      location,
      photo_url: photo_url || undefined,
      connection_degree: parsed.connection_degree,
      current_company,
      mutual_connections,
      open_to_work,
      is_hiring,
      result_urn: structured.result_urn,
      card_lines: lines.slice(0, 10),
      surface: 'public_people_search',
      page_url: normalized,
    };
  }

  window.__htLinkedInSearchCardExtractor = {
    extractCardFromAnchor,
    extractTextLines,
    parseNameLine,
    looksLikeLocation,
    NOISE_RE,
  };
})();
