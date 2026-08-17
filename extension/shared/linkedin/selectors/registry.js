/**
 * LinkedIn DOM selector registry — priority chains per surface × field.
 * @see docs/SURFACES.md
 */
(function () {
  'use strict';

  const SELECTORS = {
    public_profile: {
      ready: ['main h1', '.pv-top-card', 'main section'],
      full_name: ['main h1', 'h1.text-heading-xlarge', 'main section h1'],
      headline: [
        '.text-body-medium[data-generated-suggestion-target]',
        'main .text-body-medium.break-words',
        '.text-body-medium',
      ],
      location: [
        '.text-body-small.inline.t-black--light',
        'span.text-body-small.inline',
        'main .text-body-small.inline',
      ],
      photo: [
        'img.pv-top-card-profile-picture__image',
        '.pv-top-card__photo img',
        'main .pv-top-card img[src*="licdn"]',
      ],
      about_section: ['main a[href*="/details/about"]', 'main section'],
      experience_item: ['li.artdeco-list__item', '.pvs-list__paged-list-item', '.pvs-entity'],
    },

    public_people_search: {
      ready: [
        'main [role="listitem"] a[href*="/in/"]',
        'main a[href*="/in/"]',
        '.search-results-container',
        'main',
      ],
      result_row: ['main [role="listitem"]', '[data-chameleon-result-urn]', '[role="listitem"]'],
      profile_link: [
        'a[data-view-name="search-result-lockup-title"]',
        'a[href*="/in/"]',
      ],
      title: ['.entity-result__title-text', '.entity-result__title-line'],
      subtitle: ['.entity-result__primary-subtitle', '.entity-result__secondary-subtitle'],
      loader: ['.search-results__loader', '.artdeco-loader', '[data-test-loader]'],
      next_page: [
        'button.artdeco-pagination__button--next:not([disabled])',
        'button[aria-label="Next"]:not([disabled])',
        'button[aria-label="הבא"]:not([disabled])',
      ],
    },

    talent_profile: {
      ready: ['#profile-container', '[data-test-row-lockup-full-name]', '.artdeco-entity-lockup__title'],
      full_name: [
        '[data-test-row-lockup-full-name]',
        '#profile-container div.artdeco-entity-lockup__title',
        '#profile-container h1',
      ],
      headline: ['[data-test-row-lockup-headline]', '[data-test-row-lockup-headline] span'],
      location: ['[data-test-row-lockup-location]', 'div[data-test-row-lockup-location]'],
      public_profile_link: [
        'a[data-test-personal-info-profile-link]',
        '[data-test-public-profile-link]',
        'a[data-test-public-profile-link]',
        '.public-profile a',
      ],
      current_employer: ['[data-test-topcard-condensed-lockup-current-employer]'],
      experience_section: ['span[data-test-history-group-definition]'],
      experience_item: ['li[data-test-description-description]'],
      loader: ['.loading-overlay--is-loading', '[data-test-loader]'],
    },

    talent_search: {
      ready: ['li.profile-list', 'li[class*="profile-list"]', '.profile-list'],
      result_row: ['li.profile-list', 'li[class*="ember-view profile-list"]', 'li[class*="profile-list"]'],
      profile_link: ['a[data-test-link-to-profile-link="true"]', 'a[href*="/talent/"]'],
      loader: ['.loading-overlay--is-loading', '[data-test-loader]'],
    },

    recruiter_lite_profile: {
      ready: ['.profile-info', '.public-profile', '#artdeco-hoverable-outlet'],
      full_name: ['.profile-info h1', '#artdeco-hoverable-outlet h1', 'h1'],
      headline: ['.profile-info .title', '.profile-info h2'],
      public_profile_link: ['.public-profile a', '[data-test-public-profile-link]', 'a[data-test-public-profile-link]'],
    },

    recruiter_lite_search: {
      ready: ['.search-result-profile-link', 'a[href*="/recruiter/profile/"]'],
      result_row: ['.search-results__result-item', 'li.reusable-search__result-container'],
      profile_link: ['a.search-result-profile-link', 'a[href*="/recruiter/profile/"]'],
    },

    sales_profile: {
      ready: ['.topcard-condensed', '[data-anonymize="person-name"]', '.profile-topcard'],
      full_name: ['.topcard-condensed__heading', '[data-anonymize="person-name"]', 'h1'],
      headline: ['.topcard-condensed__headline', '[data-anonymize="headline"]'],
      location: ['.topcard-condensed__location', '[data-anonymize="location"]'],
      experience_item: ['.experience-group', '.background-entity__summary-definition--title'],
    },

    sales_search: {
      ready: ['[id="sales-api-salesApiPeopleSearch"]', '.search-results__result-list', 'ol.artdeco-list'],
      result_row: ['.search-results__result-item', 'li.artdeco-list__item'],
      profile_link: ['a[href*="/sales/people/"]', 'a[href*="/sales/lead/"]'],
      hidden_state: ['[id="sales-api-salesApiPeopleSearch"]'],
      loader: ['.artdeco-loader', '[data-test-loader]'],
    },
  };

  const READY_INDICATORS = {
    public_profile: SELECTORS.public_profile.ready,
    public_people_search: SELECTORS.public_people_search.ready,
    talent_profile: SELECTORS.talent_profile.ready,
    talent_search: SELECTORS.talent_search.ready,
    recruiter_lite_profile: SELECTORS.recruiter_lite_profile.ready,
    recruiter_lite_search: SELECTORS.recruiter_lite_search.ready,
    sales_profile: SELECTORS.sales_profile.ready,
    sales_search: SELECTORS.sales_search.ready,
  };

  window.__htLinkedInRegistry = {
    SELECTORS,
    READY_INDICATORS,
    getSurfaceSelectors(surfaceId) {
      return SELECTORS[surfaceId] || SELECTORS.public_profile;
    },
  };
})();
