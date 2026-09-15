(function () {
  'use strict';

  const SECTION_IDS = ['github', 'papers', 'community', 'cncf'];
  const PAGE_SIZE = 50;
  const DATA_ERROR = '검색 오류: 검색 데이터 형식이 올바르지 않습니다. 날짜별 목록을 이용해 주세요.';
  const ITEM_LINK = /^\.\/daily\/(\d{4}-\d{2}-\d{2})\/index\.html#(item-(github|papers|community|cncf)-[a-f0-9]{16})$/;

  function normalizeText(value) {
    return String(value == null ? '' : value).normalize('NFKC').toLowerCase();
  }

  function queryTerms(query) {
    return normalizeText(query).split(/\s+/u).filter(Boolean);
  }

  function parseFilters(hash) {
    const params = new URLSearchParams(String(hash || '').replace(/^#/, ''));
    return {
      q: params.get('q') || '',
      section: params.get('section') || '',
      tags: [...new Set(params.getAll('tag'))],
      from: params.get('from') || '',
      to: params.get('to') || '',
    };
  }

  function encodeFilters(filters) {
    const params = new URLSearchParams();
    if (filters.q) params.set('q', filters.q);
    if (filters.section) params.set('section', filters.section);
    for (const tag of new Set(filters.tags)) params.append('tag', tag);
    if (filters.from) params.set('from', filters.from);
    if (filters.to) params.set('to', filters.to);
    const encoded = params.toString();
    return encoded ? `#${encoded}` : '';
  }

  function isISODate(value) {
    if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value) || value.length !== 10) {
      return false;
    }
    const [year, month, day] = value.split('-').map(Number);
    if (year < 1 || month < 1 || month > 12 || day < 1) return false;
    const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
    const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
    return day <= days[month - 1];
  }

  function dateError(filters) {
    if (filters.from && !isISODate(filters.from)) {
      return `검색 오류: 시작 날짜가 올바르지 않습니다: ${filters.from}`;
    }
    if (filters.to && !isISODate(filters.to)) {
      return `검색 오류: 종료 날짜가 올바르지 않습니다: ${filters.to}`;
    }
    if (filters.from && filters.to && filters.from > filters.to) {
      return '검색 오류: 시작 날짜는 종료 날짜보다 늦을 수 없습니다.';
    }
    return '';
  }

  function validateFilters(filters, data) {
    if (
      !filters ||
      !['q', 'section', 'from', 'to'].every((key) => typeof filters[key] === 'string') ||
      !Array.isArray(filters.tags) ||
      !filters.tags.every((tag) => typeof tag === 'string')
    ) {
      return '검색 오류: 검색 조건의 형식이 올바르지 않습니다.';
    }
    if (filters.section && !data.sections.some((section) => section.id === filters.section)) {
      return `검색 오류: 알 수 없는 섹션입니다: ${filters.section}`;
    }
    const knownTags = new Set(data.tags.map((tag) => tag.id));
    const unknownTags = filters.tags.filter((tag) => !knownTags.has(tag));
    if (unknownTags.length) {
      return `검색 오류: 알 수 없는 태그입니다: ${unknownTags.map((tag) => tag || '(빈 값)').join(', ')}`;
    }
    return dateError(filters);
  }

  function filterItems(items, filters) {
    if (dateError(filters)) return [];
    const terms = queryTerms(filters.q);
    return items.filter((item) => {
      if (filters.section && item.section !== filters.section) return false;
      if (filters.from && item.date < filters.from) return false;
      if (filters.to && item.date > filters.to) return false;
      if (!filters.tags.every((tag) => item.tags.includes(tag))) return false;
      const text = normalizeText(item.search_text);
      return terms.every((term) => text.includes(term));
    }).sort((left, right) => {
      if (left.date === right.date) return 0;
      return left.date > right.date ? -1 : 1;
    });
  }

  function clipText(points, maxLength, start) {
    if (maxLength === 0) return '';
    if (points.length <= maxLength) return points.join('');
    if (maxLength === 1) return '…';
    const offset = Math.max(0, Math.min(start, points.length - maxLength + 1));
    const leading = offset > 0 ? '…' : '';
    const available = maxLength - leading.length;
    const trailing = offset + available < points.length ? '…' : '';
    return leading + points.slice(offset, offset + available - trailing.length).join('') + trailing;
  }

  function excerptFor(item, query, maxLength = 180) {
    const limit = Number.isFinite(maxLength) ? Math.max(0, Math.floor(maxLength)) : 180;
    const body = String(item.body || '').replace(/\s+/gu, ' ').trim();
    const normalizedBody = normalizeText(body);
    let match = -1;
    for (const term of queryTerms(query)) {
      const index = normalizedBody.indexOf(term);
      if (index !== -1 && (match === -1 || index < match)) match = index;
    }
    if (match === -1) {
      const summary = String(item.summary || '').replace(/\s+/gu, ' ').trim();
      return clipText(Array.from(summary), limit, 0);
    }
    const points = Array.from(body);
    // Map the normalized match back to the original codepoints, including decomposed Korean.
    let low = 0;
    let high = points.length;
    while (low < high) {
      const middle = Math.ceil((low + high) / 2);
      if (normalizeText(points.slice(0, middle).join('')).length <= match) low = middle;
      else high = middle - 1;
    }
    return clipText(points, limit, Math.max(0, low - Math.floor(limit / 3)));
  }

  function record(value) {
    return value !== null && typeof value === 'object' && !Array.isArray(value);
  }

  function validItemLink(item) {
    if (typeof item.href !== 'string') return false;
    const match = ITEM_LINK.exec(item.href);
    return Boolean(
      match &&
      match[0] === item.href &&
      isISODate(match[1]) &&
      match[1] === item.date &&
      match[3] === item.section &&
      item.id === `${item.date}:${match[2]}`
    );
  }

  function validData(data) {
    if (
      !record(data) || data.version !== 1 ||
      !Array.isArray(data.sections) || data.sections.length !== SECTION_IDS.length ||
      !Array.isArray(data.tags) || !Array.isArray(data.items)
    ) return false;
    let reportDates = null;
    if (Object.hasOwn(data, 'report_dates')) {
      if (!Array.isArray(data.report_dates) || !data.report_dates.every(isISODate)) return false;
      reportDates = new Set(data.report_dates);
      if (reportDates.size !== data.report_dates.length) return false;
    }
    const sectionIds = new Set();
    for (const section of data.sections) {
      if (
        !record(section) || !SECTION_IDS.includes(section.id) ||
        typeof section.label !== 'string' || !section.label.trim() ||
        sectionIds.has(section.id)
      ) return false;
      sectionIds.add(section.id);
    }
    const tagIds = new Set();
    for (const tag of data.tags) {
      if (
        !record(tag) || typeof tag.id !== 'string' || !tag.id.trim() ||
        typeof tag.label !== 'string' || !tag.label.trim() ||
        !Array.isArray(tag.aliases) || !tag.aliases.every((alias) => typeof alias === 'string') ||
        !Number.isSafeInteger(tag.count) || tag.count < 1 || tagIds.has(tag.id)
      ) return false;
      tagIds.add(tag.id);
    }
    const itemIds = new Set();
    for (const item of data.items) {
      if (
        !record(item) ||
        !['id', 'date', 'section', 'section_label', 'title', 'issue_title', 'summary', 'body', 'search_text']
          .every((key) => typeof item[key] === 'string') ||
        !item.title.trim() || !item.section_label.trim() ||
        !sectionIds.has(item.section) || !isISODate(item.date) ||
        (reportDates && !reportDates.has(item.date)) ||
        !Array.isArray(item.tags) || !item.tags.every((tag) => tagIds.has(tag)) ||
        new Set(item.tags).size !== item.tags.length ||
        itemIds.has(item.id) || !validItemLink(item)
      ) return false;
      itemIds.add(item.id);
    }
    return true;
  }

  function mountSearch(document, location, history) {
    const root = document.getElementById('archive-search');
    if (!root) return false;
    const element = (tag, className, text) => {
      const node = document.createElement(tag);
      if (className) node.className = className;
      if (text !== undefined) node.textContent = text;
      return node;
    };
    let status = document.getElementById('search-status');
    if (!status) {
      status = element('p');
      status.id = 'search-status';
      status.setAttribute('role', 'status');
      status.setAttribute('aria-live', 'polite');
      root.appendChild(status);
    }
    function setStatus(message, error = false) {
      status.textContent = message;
      status.dataset.error = String(error);
    }
    const results = document.getElementById('search-results');
    const archive = document.getElementById('date-archive');
    const more = document.getElementById('search-more');
    function showDataError(message) {
      setStatus(message, true);
      if (results) {
        results.replaceChildren();
        results.hidden = true;
      }
      if (archive) archive.hidden = false;
      if (more) more.hidden = true;
    }
    const dataNode = document.getElementById('search-data');
    const form = document.getElementById('search-form');
    const queryInput = document.getElementById('search-query');
    const sectionInput = document.getElementById('search-section');
    const fromInput = document.getElementById('search-from');
    const toInput = document.getElementById('search-to');
    const tagsInput = document.getElementById('search-tags');
    const reset = document.getElementById('search-reset');
    // Even unusable data must not turn the search form into a network submission.
    if (form) form.addEventListener('submit', (event) => event.preventDefault());
    if (
      ![results, archive, more, dataNode, form, queryInput, sectionInput, fromInput, toInput, tagsInput, reset]
        .every(Boolean)
    ) {
      showDataError('검색 오류: 검색 화면을 준비할 수 없습니다. 날짜별 목록을 이용해 주세요.');
      return false;
    }
    let data;
    try {
      data = JSON.parse(dataNode.textContent);
    } catch {
      showDataError('검색 오류: 검색 데이터를 읽을 수 없습니다. 날짜별 목록을 이용해 주세요.');
      return false;
    }
    if (!validData(data)) {
      showDataError(DATA_ERROR);
      return false;
    }

    const tagsById = new Map(data.tags.map((tag) => [tag.id, tag]));
    const reportCount = data.report_dates === undefined
      ? new Set(data.items.map((item) => item.date)).size
      : data.report_dates.length;
    let currentFilters = parseFilters(location.hash);
    let visibleLimit = PAGE_SIZE;

    function syncDateInput(input, value) {
      const invalid = Boolean(value && !isISODate(value));
      // Native date inputs erase malformed hash values; keep them visible and editable.
      input.type = invalid ? 'text' : 'date';
      input.value = value;
      input.setAttribute('aria-invalid', invalid ? 'true' : 'false');
    }

    function syncControls() {
      queryInput.value = currentFilters.q;
      sectionInput.replaceChildren();
      const allSections = element('option', '', '전체 섹션');
      allSections.value = '';
      sectionInput.appendChild(allSections);
      const unknownSection = currentFilters.section &&
        !data.sections.some((section) => section.id === currentFilters.section);
      for (const section of data.sections) {
        const option = element('option', '', section.label);
        option.value = section.id;
        sectionInput.appendChild(option);
      }
      if (unknownSection) {
        const option = element('option', '', `알 수 없는 섹션: ${currentFilters.section}`);
        option.value = currentFilters.section;
        sectionInput.appendChild(option);
      }
      sectionInput.value = currentFilters.section;
      sectionInput.setAttribute('aria-invalid', unknownSection ? 'true' : 'false');
      syncDateInput(fromInput, currentFilters.from);
      syncDateInput(toInput, currentFilters.to);
      tagsInput.replaceChildren();
      const tagOptions = [...data.tags];
      for (const id of currentFilters.tags) {
        if (!tagsById.has(id)) tagOptions.push({ id, label: `알 수 없는 태그: ${id || '(빈 값)'}` });
      }
      if (!tagOptions.length) {
        tagsInput.appendChild(element('p', 'meta', '첫 보고서가 게시되면 태그가 표시됩니다.'));
      }
      for (const tag of tagOptions) {
        const label = element('label', 'tag-option');
        const input = element('input');
        input.type = 'checkbox';
        input.name = 'tag';
        input.value = tag.id;
        input.checked = currentFilters.tags.includes(tag.id);
        if (!tagsById.has(tag.id)) input.setAttribute('aria-invalid', 'true');
        label.appendChild(input);
        label.appendChild(element('span', '', ` ${tag.label} `));
        if (tagsById.has(tag.id)) label.appendChild(element('span', 'tag-count', String(tag.count)));
        tagsInput.appendChild(label);
      }
    }

    function updateHash() {
      history.replaceState(
        history.state,
        '',
        (location.pathname || '') + (location.search || '') + encodeFilters(currentFilters)
      );
    }

    function useFilters(filters) {
      currentFilters = filters;
      visibleLimit = PAGE_SIZE;
      syncControls();
      updateHash();
      render();
    }

    function resultArticle(item) {
      if (!validItemLink(item)) return null;
      const article = element('article', 'search-result');
      article.appendChild(element('p', 'meta', `${item.date} · ${item.section_label}`));
      const heading = element('h3');
      const link = element('a', '', item.title);
      link.setAttribute('href', item.href);
      heading.appendChild(link);
      article.appendChild(heading);
      article.appendChild(element('p', 'search-excerpt', excerptFor(item, currentFilters.q)));
      const tagList = element('div', 'tag-list');
      for (const id of item.tags) {
        const chip = element('button', 'tag-chip', tagsById.get(id).label);
        chip.type = 'button';
        chip.dataset.tag = id;
        chip.addEventListener('click', () => {
          useFilters({ ...currentFilters, tags: [...new Set([...currentFilters.tags, id])] });
        });
        tagList.appendChild(chip);
      }
      article.appendChild(tagList);
      return article;
    }

    function render() {
      results.replaceChildren();
      more.hidden = true;
      const active = Boolean(
        currentFilters.q || currentFilters.section || currentFilters.tags.length ||
        currentFilters.from || currentFilters.to
      );
      archive.hidden = active && data.items.length > 0;
      results.hidden = !active || data.items.length === 0;
      const error = validateFilters(currentFilters, data);
      if (error) {
        setStatus(error, true);
        return;
      }
      if (!data.items.length) {
        setStatus(reportCount > 0
          ? `공개 보고서 ${reportCount}개 · 검색 가능한 항목 0개. 날짜별 목록에서 수집 결과를 확인하세요.`
          : '아직 공개된 보고서가 없습니다. 첫 보고서가 게시되면 검색할 수 있습니다.');
        return;
      }
      if (!active) {
        setStatus(`공개 보고서 ${reportCount}개 · 항목 ${data.items.length}개. 검색어나 태그로 찾아보세요.`);
        return;
      }
      const matches = filterItems(data.items, currentFilters);
      if (!matches.length) {
        setStatus('검색 결과가 없습니다. 검색어 또는 필터를 바꿔보세요.');
        return;
      }
      for (const item of matches.slice(0, visibleLimit)) {
        const article = resultArticle(item);
        if (!article) {
          showDataError(DATA_ERROR);
          return;
        }
        results.appendChild(article);
      }
      setStatus(`검색 결과 ${matches.length}개 · 최신순`);
      more.hidden = visibleLimit >= matches.length;
    }

    function readControls() {
      currentFilters = {
        q: queryInput.value,
        section: sectionInput.value,
        tags: Array.from(tagsInput.querySelectorAll('input[name="tag"]'))
          .filter((input) => input.checked).map((input) => input.value),
        from: fromInput.value,
        to: toInput.value,
      };
      visibleLimit = PAGE_SIZE;
      sectionInput.setAttribute(
        'aria-invalid',
        currentFilters.section && !data.sections.some((section) => section.id === currentFilters.section)
          ? 'true' : 'false'
      );
      syncDateInput(fromInput, currentFilters.from);
      syncDateInput(toInput, currentFilters.to);
      updateHash();
      render();
    }

    function restoreHash() {
      currentFilters = parseFilters(location.hash);
      visibleLimit = PAGE_SIZE;
      syncControls();
      render();
    }

    form.addEventListener('input', readControls);
    form.addEventListener('change', readControls);
    form.addEventListener('submit', readControls);
    form.addEventListener('reset', (event) => {
      event.preventDefault();
      useFilters(parseFilters(''));
    });
    reset.addEventListener('click', () => useFilters(parseFilters('')));
    more.addEventListener('click', () => {
      visibleLimit += PAGE_SIZE;
      render();
    });
    if (document.defaultView) {
      document.defaultView.addEventListener('hashchange', restoreHash);
      document.defaultView.addEventListener('popstate', restoreHash);
    }
    restoreHash();
    return true;
  }

  const api = { normalizeText, parseFilters, validateFilters, filterItems, excerptFor, encodeFilters, mountSearch };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof document !== 'undefined') {
    const start = () => mountSearch(document, document.defaultView.location, document.defaultView.history);
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, { once: true });
    else start();
  }
})();
