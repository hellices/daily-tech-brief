(function () {
  'use strict';

  function searchDestination(base, query) {
    const value = query.trim();
    return base + (value ? '#' + new URLSearchParams({ q: value }).toString() : '#archive-search');
  }

  function activeSection(headings, threshold) {
    if (!headings.length) return null;
    let current = headings[0].id;
    for (const heading of headings) {
      if (heading.top <= threshold) current = heading.id;
    }
    return current;
  }

  function fragmentTarget(hash) {
    const fragment = hash.replace(/^#/, '');
    if (!fragment) return null;
    return fragment.includes('=') ? 'archive-search' : fragment;
  }

  function setupNavigationMenu(menu, document) {
    if (!menu) return;
    const summary = menu.querySelector('summary');
    document.addEventListener('pointerdown', (event) => {
      if (menu.open && !menu.contains(event.target)) menu.open = false;
    });
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && menu.open) {
        event.preventDefault();
        menu.open = false;
        summary.focus();
      }
    });
    menu.querySelectorAll('a').forEach((anchor) => {
      anchor.addEventListener('click', () => { menu.open = false; });
    });
  }

  function mountReader(document, window) {
    setupNavigationMenu(document.getElementById('report-menu'), document);
    const form = document.getElementById('header-search');
    const query = document.getElementById('header-search-query');
    const searchLink = document.querySelector('[data-header-search-link]');
    const localQuery = document.getElementById('search-query');
    const stickyHeader = document.querySelector('.site-header');
    document.documentElement.style.setProperty(
      '--reader-header-height',
      (stickyHeader ? stickyHeader.getBoundingClientRect().height : 0) + 'px'
    );
    const isEditable = (element) => element && (
      ['INPUT', 'TEXTAREA', 'SELECT'].includes(element.tagName) || element.isContentEditable
    );
    const closeMenus = () => {
      document.querySelectorAll('.mobile-outline[open]').forEach((menu) => {
        menu.open = false;
      });
    };

    if (form && query) {
      form.addEventListener('submit', (event) => {
        event.preventDefault();
        window.location.assign(searchDestination(form.dataset.searchBase, query.value));
        if (localQuery) {
          localQuery.value = query.value.trim();
          localQuery.dispatchEvent(new window.Event('input', { bubbles: true }));
          localQuery.focus({ preventScroll: true });
          document.getElementById('archive-search').scrollIntoView();
        }
      });
      document.addEventListener('keydown', (event) => {
        const find = event.key === '/' && !event.ctrlKey && !event.metaKey && !event.altKey;
        const shortcut = event.key.toLowerCase() === 'k' && (event.ctrlKey || event.metaKey);
        if ((find || shortcut) && !isEditable(event.target)) {
          event.preventDefault();
          query.focus();
          query.select();
        }
        if (event.key === 'Escape' && event.target === query) {
          query.blur();
          if (searchLink) searchLink.focus();
        }
      });
    }
    function revealFragment() {
      const fragment = fragmentTarget(window.location.hash);
      if (!fragment) return;
      const target = document.getElementById(fragment);
      if (!target) return;
      if (fragment.startsWith('item-')) {
        for (let parent = target.parentElement; parent; parent = parent.parentElement) {
          if (parent.tagName === 'DETAILS') parent.open = true;
        }
      }
      if (fragment === 'archive-search' && localQuery) localQuery.focus({ preventScroll: true });
      target.scrollIntoView();
    }
    document.querySelectorAll('.mobile-outline a').forEach((anchor) => {
      anchor.addEventListener('click', closeMenus);
    });
    window.addEventListener('hashchange', revealFragment);
    revealFragment();

    const links = Array.from(document.querySelectorAll('[data-outline-link]'));
    const targets = [...new Set(links.map((anchor) => anchor.dataset.outlineLink))]
      .map((id) => document.getElementById(id)).filter(Boolean);
    let pending = false;
    function updateOutline() {
      pending = false;
      const headerHeight = stickyHeader ? stickyHeader.getBoundingClientRect().height : 0;
      document.documentElement.style.setProperty('--reader-header-height', headerHeight + 'px');
      const threshold = headerHeight + 32;
      const headings = targets.filter((target) => target.getClientRects().length > 0)
        .map((target) => ({ id: target.id, top: target.getBoundingClientRect().top }));
      const active = activeSection(headings, threshold);
      for (const anchor of links) {
        if (anchor.dataset.outlineLink === active) anchor.setAttribute('aria-current', 'location');
        else anchor.removeAttribute('aria-current');
      }
    }
    function requestUpdate() {
      if (!pending) {
        pending = true;
        window.requestAnimationFrame(updateOutline);
      }
    }
    window.addEventListener('scroll', requestUpdate, { passive: true });
    window.addEventListener('resize', requestUpdate, { passive: true });
    document.addEventListener('toggle', requestUpdate, true);
    updateOutline();
    const urlQuery = new URLSearchParams(window.location.search).get('q');
    if (urlQuery && localQuery && !window.location.hash) {
      window.location.hash = new URLSearchParams({ q: urlQuery }).toString();
    }
  }

  if (typeof module !== 'undefined' && module.exports) module.exports = { searchDestination, activeSection, fragmentTarget, setupNavigationMenu };
  if (typeof document !== 'undefined') {
    const start = () => mountReader(document, window);
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, { once: true });
    else start();
  }
})();
