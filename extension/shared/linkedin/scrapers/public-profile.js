/**
 * Public LinkedIn profile scraper — semantic sections + innerText (ported from extension-v3).
 */
(function () {
  'use strict';

  const textApi = () => window.__htLinkedInText;
  const cleanLine = (v) => textApi()?.cleanLine(v) ?? String(v || '').trim();
  const visibleLines = (el) => textApi()?.visibleLines(el) ?? [];
  const ariaText = (scope, sel) => textApi()?.ariaText(scope, sel) ?? '';
  const delay = (ms) => textApi()?.delay(ms) ?? new Promise((r) => setTimeout(r, ms));

  const SECTION_ALIASES = {
    about: ['about', 'אודות', 'עלי', 'summary'],
    experience: ['experience', 'ניסיון', 'ניסיון תעסוקתי', 'work experience'],
    education: ['education', 'השכלה', 'לימודים'],
    skills: ['skills', 'מיומנויות'],
    licenses_and_certifications: ['certifications', 'licenses', 'הסמכות', 'רישיונות'],
    languages: ['languages', 'שפות'],
    projects: ['projects', 'פרויקטים'],
    volunteering_experience: ['volunteering', 'התנדבות'],
    honors_and_awards: ['honors', 'awards', 'פרסים', 'הישגים'],
    recommendations: ['recommendations', 'המלצות'],
  };

  const DETAILS_PATHS = {
    experience: ['experience'],
    education: ['education'],
    skills: ['skills'],
    licenses_and_certifications: ['certifications'],
    languages: ['languages'],
    projects: ['projects'],
    volunteering_experience: ['volunteering-experiences', 'volunteering'],
    honors_and_awards: ['honors'],
    recommendations: ['recommendations'],
  };

  function headingMatches(txt, sectionId) {
    const t = cleanLine(txt).toLowerCase();
    if (!t) return false;
    const norm = sectionId.replace(/_/g, ' ').toLowerCase();
    if (t === norm || t.startsWith(norm)) return true;
    return (SECTION_ALIASES[sectionId] || []).some((a) => {
      const x = a.toLowerCase();
      return t === x || t.startsWith(x) || t.includes(x);
    });
  }

  function findByDetailsLink(sectionId) {
    for (const path of DETAILS_PATHS[sectionId] || []) {
      const links = document.querySelectorAll(`main a[href*="/details/${path}/"]`);
      for (const link of links) {
        if (/\/edit\//.test(link.getAttribute('href') || '')) continue;
        const sec = link.closest('section');
        if (sec) return sec;
      }
    }
    return null;
  }

  function findSection(sectionId) {
    const byDetails = findByDetailsLink(sectionId);
    if (byDetails) return byDetails;
    const hash = document.querySelector(`#${sectionId}, [id="${sectionId}"]`);
    if (hash) return hash.closest('section') || hash;
    for (const h of document.querySelectorAll('main section h2, main section h3')) {
      if (headingMatches(h.textContent, sectionId)) return h.closest('section');
    }
    for (const sec of document.querySelectorAll('main section')) {
      const h = sec.querySelector('h2, h3');
      if (h && headingMatches(h.textContent, sectionId)) return sec;
    }
    return null;
  }

  function looksLikeLocation(line) {
    return /,/.test(line) && !/·/.test(line) && line.length <= 80;
  }

  function looksLikeDateRange(line) {
    if (!/[-–—]/.test(line) && !/(present|נוכחי)/i.test(line)) return false;
    return /(\b\d{4}\b|present|נוכחי|mos?\b|yrs?\b|חודש|שנה)/i.test(line);
  }

  function extractBasicInfo() {
    const info = {};
    const topCard =
      document.querySelector('main a[href*="/overlay/contact-info"]')?.closest('section') || null;
    const nameEl =
      document.querySelector('main h1') ||
      topCard?.querySelector('h1, h2') ||
      document.querySelector('h1.text-heading-xlarge, main section h1');

    if (nameEl) info.full_name = ariaText(nameEl) || cleanLine(nameEl.textContent);
    else info.full_name = cleanLine((document.title || '').split('|')[0]);

    const headlineEl =
      document.querySelector('.text-body-medium[data-generated-suggestion-target]') ||
      document.querySelector('main .text-body-medium.break-words, .text-body-medium');
    if (headlineEl) info.headline = ariaText(headlineEl) || cleanLine(headlineEl.textContent);

    const locEl = document.querySelector(
      '.text-body-small.inline.t-black--light, span.text-body-small.inline',
    );
    if (locEl) info.location = ariaText(locEl) || cleanLine(locEl.textContent);

    const photoEl = document.querySelector(
      'img.pv-top-card-profile-picture__image, .pv-top-card__photo img, main .pv-top-card img[src*="licdn"]',
    );
    if (photoEl?.src && !photoEl.src.includes('data:') && !/ghost|default/i.test(photoEl.src)) {
      info.photo_url = photoEl.src;
    }
    return info;
  }

  function extractExperience(section) {
    const items = [];
    for (const entry of section.querySelectorAll('li.artdeco-list__item, .pvs-entity')) {
      const title = ariaText(entry, '.t-bold span[aria-hidden="true"]') ||
        entry.querySelector('.t-bold')?.textContent?.trim();
      const companyEl = entry.querySelector('.t-14.t-normal span[aria-hidden="true"]');
      const company = companyEl ? cleanLine(companyEl.textContent).split('·')[0] : '';
      if (title || company) items.push({ title: title || '', company: company || '', duration: '', description: '' });
    }
    if (items.length) return items;
    const lines = visibleLines(section).filter((l) => !headingMatches(l, 'experience'));
    let buf = [];
    for (const line of lines) {
      buf.push(line);
      if (looksLikeDateRange(line) && buf.length >= 2) {
        items.push({ title: buf[0], company: buf[1], duration: line, description: buf.slice(2).join(' ') });
        buf = [];
      }
    }
    return items;
  }

  function extractListSection(section, max = 15) {
    const items = [];
    for (const li of section.querySelectorAll('li.artdeco-list__item, .pvs-list__paged-list-item')) {
      const lines = visibleLines(li);
      if (lines.length) items.push({ title: lines[0], subtitle: lines[1] || '' });
      if (items.length >= max) break;
    }
    return items;
  }

  function extractSkills(section) {
    const skills = [];
    for (const li of section.querySelectorAll('li')) {
      const name = ariaText(li, '.t-bold span[aria-hidden="true"]') || visibleLines(li)[0];
      if (name) skills.push(name);
      if (skills.length >= 25) break;
    }
    return skills;
  }

  function buildRawText(profile) {
    const blocks = [];
    if (profile.about) blocks.push(`=== ABOUT ===\n${profile.about}`);
    if (profile.experience?.length) {
      blocks.push(`=== EXPERIENCE ===\n${profile.experience.map((e) => `${e.title} @ ${e.company}`).join('\n')}`);
    }
    if (profile.skills?.length) blocks.push(`=== SKILLS ===\n${profile.skills.join(', ')}`);
    const t = blocks.join('\n\n');
    return t.length > 15000 ? `${t.slice(0, 15000)}…` : t;
  }

  async function scrollToLoad() {
    const total = Math.max(document.body.scrollHeight, document.documentElement.scrollHeight);
    const step = Math.floor(window.innerHeight * 0.85) || 600;
    for (let pos = 0; pos < total; pos += step) {
      window.scrollTo(0, pos);
      await delay(450);
    }
    window.scrollTo(0, 0);
    await delay(700);
  }

  async function expandSeeMore() {
    const SEE_MORE = textApi()?.SEE_MORE;
    const buttons = document.querySelectorAll(
      'button[aria-label*="see more" i], button[aria-label*="עוד" i]',
    );
    for (const btn of buttons) {
      try {
        btn.click();
        await delay(280);
      } catch (_) { /* skip */ }
    }
  }

  async function preparePage(opts = {}) {
    await delay(opts.initialWait || 1500);
    await scrollToLoad();
    await expandSeeMore();
    if (opts.extraWait) await delay(opts.extraWait);
  }

  function extractProfile() {
    const profile = {
      source: 'linkedin_profile',
      linkedin_url: `${location.href.split('?')[0].replace(/\/$/, '')}/`,
      extracted_at: new Date().toISOString(),
      scraped_via: 'dom',
      ...extractBasicInfo(),
      about: '',
      experience: [],
      education: [],
      skills: [],
      certifications: [],
    };

    const aboutSec = findSection('about');
    if (aboutSec) {
      const span = aboutSec.querySelector('.inline-show-more-text span[aria-hidden="true"]');
      profile.about = span ? cleanLine(span.textContent) : visibleLines(aboutSec).slice(1).join('\n');
    }

    const expSec = findSection('experience');
    if (expSec) profile.experience = extractExperience(expSec);

    const eduSec = findSection('education');
    if (eduSec) profile.education = extractListSection(eduSec, 20);

    const skillsSec = findSection('skills');
    if (skillsSec) profile.skills = extractSkills(skillsSec);

    const certSec = findSection('licenses_and_certifications');
    if (certSec) profile.certifications = extractListSection(certSec, 20);

    profile.raw_text = buildRawText(profile);
    return profile;
  }

  async function extractProfileFull() {
    const profile = extractProfile();
    const detailsApi = window.__htLinkedInDetails;
    if (!detailsApi?.scrapeAll) return profile;

    const deep = await detailsApi.scrapeAll(profile.linkedin_url);
    if (deep.skills?.length) profile.skills = [...new Set([...(profile.skills || []), ...deep.skills])];
    if (deep.experience?.length) profile.experience = [...(profile.experience || []), ...deep.experience];
    profile.extraction_depth = 'full';
    profile.raw_text = buildRawText(profile);
    return profile;
  }

  function isProfileEmpty(data) {
    if (!data) return true;
    return !data.full_name && !(data.experience?.length) && !(data.raw_text?.length > 80);
  }

  window.__htLinkedInPublicProfile = {
    preparePage,
    extractProfile,
    extractProfileFull,
    isProfileEmpty,
  };

  // Back-compat alias used by profile-details deep scrape chain
  window.__htLinkedInScraper = window.__htLinkedInPublicProfile;
})();
