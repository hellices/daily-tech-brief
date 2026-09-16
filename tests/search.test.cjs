const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {
  normalizeText,
  parseFilters,
  validateFilters,
  filterItems,
  excerptFor,
  encodeFilters,
  mountSearch,
} = require('../search.js');

const sections = [
  { id: 'github', label: 'GitHub' },
  { id: 'papers', label: '논문' },
  { id: 'community', label: '커뮤니티' },
  { id: 'cncf', label: 'CNCF' },
];

function item(date, section, suffix, tags, searchText, overrides = {}) {
  const anchor = `item-${section}-${suffix.padStart(16, '0')}`;
  return {
    id: `${date}:${anchor}`,
    date,
    section,
    section_label: sections.find((entry) => entry.id === section).label,
    title: `제목 ${suffix}`,
    issue_title: `${date} · 오늘의 보고서`,
    summary: '검색 결과의 요약입니다.',
    body: '본문에 에이전트의 메모리 설계를 설명합니다.',
    search_text: searchText,
    tags,
    href: `./daily/${date}/index.html#${anchor}`,
    ...overrides,
  };
}

function fixture() {
  return {
    version: 1,
    sections: structuredClone(sections),
    tags: [
      { id: 'agent', label: '에이전트', aliases: ['agent', 'agents'], count: 3 },
      { id: 'memory', label: '메모리', aliases: ['memory'], count: 2 },
    ],
    items: [
      item('2026-09-14', 'community', '1', ['agent'], 'agent 에이전트 커뮤니티'),
      item('2026-09-16', 'github', '2', ['agent', 'memory'], 'Agent 에이전트 memory 메모리'),
      item('2026-09-16', 'papers', '3', ['agent', 'memory'], 'AGENT 에이전트 Memory 메모리 논문'),
      item('2026-09-15', 'cncf', '4', [], 'cloud 클라우드'),
    ],
  };
}

function filters(overrides = {}) {
  return { q: '', section: '', tags: [], from: '', to: '', ...overrides };
}

test('normalization handles case, compatibility forms, and decomposed Korean', () => {
  assert.equal(normalizeText('ＡＧＥＮＴ 메모리'.normalize('NFD')), 'agent 메모리');
  assert.equal(normalizeText(null), '');
  assert.equal(normalizeText(undefined), '');
  assert.equal(normalizeText(42), '42');
});

test('all literal query terms must match the precombined Korean/English search text', () => {
  const data = fixture();
  assert.deepEqual(
    filterItems(data.items, filters({ q: '  aGeNt\t메모리\n' })).map((entry) => entry.section),
    ['github', 'papers'],
  );
  assert.equal(filterItems(data.items, filters({ q: 'agent cloud' })).length, 0);
  assert.equal(
    filterItems(data.items, filters({ q: '에이전트 메모리'.normalize('NFD') })).length,
    2,
  );
  data.items[1].search_text = data.items[1].search_text.normalize('NFD');
  assert.equal(filterItems(data.items, filters({ q: '메모리' })).length, 2);
});

test('canonical tags intersect and combine with query, section, and inclusive dates', () => {
  const data = fixture();
  assert.equal(filterItems(data.items, filters({ tags: ['agent', 'memory'] })).length, 2);
  assert.deepEqual(
    filterItems(data.items, filters({
      q: 'memory 에이전트',
      tags: ['agent', 'memory'],
      section: 'papers',
      from: '2026-09-16',
      to: '2026-09-16',
    })).map((entry) => entry.section),
    ['papers'],
  );
  assert.equal(filterItems(data.items, filters({ tags: ['메모리'] })).length, 0);
});

test('date endpoints are inclusive and optional', () => {
  const items = fixture().items;
  assert.equal(filterItems(items, filters({ from: '2026-09-15', to: '2026-09-16' })).length, 3);
  assert.equal(filterItems(items, filters({ from: '2026-09-16' })).length, 2);
  assert.equal(filterItems(items, filters({ to: '2026-09-14' })).length, 1);
});

test('sort is newest-first, preserves same-day order, and does not mutate inputs', () => {
  const items = fixture().items;
  const before = structuredClone(items);
  const result = filterItems(items, filters());
  assert.deepEqual(result.map((entry) => entry.section), ['github', 'papers', 'cncf', 'community']);
  assert.deepEqual(items, before);
  assert.notEqual(result, items);
});

test('query regex metacharacters and markup are literal, not executable expressions', () => {
  const items = [
    item('2026-09-16', 'github', 'a', [], 'literal [.*] <img onerror=alert(1)>'),
    item('2026-09-16', 'github', 'b', [], 'unrelated text'),
  ];
  assert.equal(filterItems(items, filters({ q: '[.*]' })).length, 1);
  assert.equal(filterItems(items, filters({ q: '<img onerror=alert(1)>' })).length, 1);
  assert.equal(filterItems(items, filters({ q: '(' })).length, 1);
  assert.equal(filterItems(items, filters({ q: '^unrelated$' })).length, 0);
});

test('filter validation rejects unknown tags and sections rather than broadening', () => {
  const data = fixture();
  assert.equal(validateFilters(filters(), data), '');
  assert.equal(validateFilters(filters({ tags: ['memory'], section: 'papers' }), data), '');
  for (const invalid of [
    { tags: ['unknown'] },
    { tags: [''] },
    { tags: ['agent', '메모리'] },
    { section: 'unknown' },
  ]) {
    assert.match(validateFilters(filters(invalid), data), /태그|섹션/);
  }
});

test('date validation uses the calendar, including leap years, without rollover', () => {
  const data = fixture();
  for (const date of ['2024-02-29', '2000-02-29', '2026-09-16']) {
    assert.equal(validateFilters(filters({ from: date, to: date }), data), '');
  }
  for (const date of [
    '2026-02-29', '1900-02-29', '2026-04-31', '2026-13-01',
    '2026-00-01', '2026-09-00', '0000-01-01', '2026-9-01',
    '2026-09-01T00:00:00Z', '2026-09-01\n', 'not-a-date',
  ]) {
    assert.match(validateFilters(filters({ from: date }), data), /날짜/);
    assert.match(validateFilters(filters({ to: date }), data), /날짜/);
  }
  assert.match(
    validateFilters(filters({ from: '2026-09-17', to: '2026-09-16' }), data),
    /시작.*종료|날짜/,
  );
});

test('invalid date ranges cannot produce unfiltered results', () => {
  const items = fixture().items;
  assert.deepEqual(filterItems(items, filters({ from: '2026-09-17', to: '2026-09-16' })), []);
  assert.deepEqual(filterItems(items, filters({ from: 'invalid' })), []);
});

test('hash filters round-trip Unicode, repeated tags, dates, and reserved characters', () => {
  const state = filters({
    q: '메모리 C++ & # <text>',
    section: 'papers',
    tags: ['agent', 'memory'],
    from: '2026-09-01',
    to: '2026-09-16',
  });
  const hash = encodeFilters(state);
  assert.ok(hash.startsWith('#q='));
  assert.match(hash, /tag=agent&tag=memory/);
  assert.deepEqual(parseFilters(hash), state);
  assert.deepEqual(parseFilters(hash.slice(1)), state);
  assert.deepEqual(parseFilters(''), filters());
  assert.equal(encodeFilters(filters()), '');
});

test('hash parsing retains unknown/invalid filters for visible validation', () => {
  assert.deepEqual(
    parseFilters('#q=agent&section=not-real&tag=unknown&from=bad'),
    filters({ q: 'agent', section: 'not-real', tags: ['unknown'], from: 'bad' }),
  );
  assert.deepEqual(parseFilters('#tag=memory&tag=memory').tags, ['memory']);
  assert.deepEqual(parseFilters('#tag=').tags, ['']);
});

test('excerpts find the earliest literal query match in body, otherwise use summary', () => {
  const entry = {
    body: `${'앞'.repeat(230)} MEMORY 중요한 대목 ${'뒤'.repeat(230)}`,
    summary: '대체 요약',
  };
  const excerpt = excerptFor(entry, 'missing memory');
  assert.match(excerpt, /MEMORY 중요한 대목/);
  assert.ok(excerpt.startsWith('…'));
  assert.ok(excerpt.endsWith('…'));
  assert.ok(Array.from(excerpt).length <= 180);
  assert.equal(excerptFor(entry, 'not-present'), '대체 요약');
  assert.equal(excerptFor(entry, ''), '대체 요약');
  assert.match(
    excerptFor({ body: `${'a'.repeat(220)} first ${'b'.repeat(220)} second`, summary: '' }, 'second first'),
    /first/,
  );
});

test('excerpts preserve Unicode codepoints, including astral and NFD Korean text', () => {
  const entry = {
    body: `${'😀'.repeat(200)} ${'메모리'.normalize('NFD')} ${'🚀'.repeat(200)}`,
    summary: '🧑'.repeat(200),
  };
  const excerpt = excerptFor(entry, '메모리', 80);
  assert.ok(normalizeText(excerpt).includes('메모리'));
  assert.ok(Array.from(excerpt).length <= 80);
  assert.ok(excerpt.isWellFormed());
  const fallback = excerptFor(entry, 'missing', 9);
  assert.ok(Array.from(fallback).length <= 9);
  assert.ok(fallback.isWellFormed());
  assert.equal(excerptFor(entry, '메모리', 0), '');
  assert.ok(Array.from(excerptFor(entry, '메모리', 1)).length <= 1);
});

class Element {
  constructor(tagName = 'div') {
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.listeners = new Map();
    this.attributes = new Map();
    this.hidden = false;
    this.value = '';
    this.checked = false;
    this.className = '';
    this.dataset = {};
    this._text = '';
  }
  set textContent(value) {
    this._text = String(value);
    this.children = [];
  }
  get textContent() {
    return this._text + this.children.map((child) => child.textContent).join('');
  }
  set innerHTML(_) {
    throw new Error('HTML injection sink must not be used');
  }
  appendChild(child) {
    this.children.push(child);
    return child;
  }
  replaceChildren(...children) {
    this._text = '';
    this.children = children;
  }
  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }
  removeAttribute(name) {
    this.attributes.delete(name);
  }
  getAttribute(name) {
    return this.attributes.get(name) ?? null;
  }
  addEventListener(name, listener) {
    const listeners = this.listeners.get(name) || [];
    listeners.push(listener);
    this.listeners.set(name, listeners);
  }
  dispatch(name, values = {}) {
    const event = {
      target: this,
      defaultPrevented: false,
      preventDefault() { this.defaultPrevented = true; },
      ...values,
    };
    for (const listener of this.listeners.get(name) || []) listener(event);
    return event;
  }
  querySelectorAll(selector) {
    const result = [];
    for (const child of this.children) {
      if (child.tagName === 'INPUT' && (!selector.includes(':checked') || child.checked)) {
        result.push(child);
      }
      result.push(...child.querySelectorAll(selector));
    }
    return result;
  }
}

function browser(data = fixture(), hash = '', missingIds = []) {
  const ids = [
    'archive-search', 'search-data', 'search-form', 'search-query', 'search-section',
    'search-from', 'search-to', 'search-tags', 'search-reset', 'search-status',
    'search-results', 'search-more', 'date-archive',
  ];
  const nodes = Object.fromEntries(ids.map((id) => [id, new Element()]));
  nodes['search-data'].textContent = typeof data === 'string' ? data : JSON.stringify(data);
  for (const id of missingIds) delete nodes[id];
  const view = new Element();
  const location = { hash, pathname: '/index.html', search: '?scoutTheme=dark' };
  const calls = [];
  const history = {
    state: { retained: true },
    replaceState(state, unused, url) {
      calls.push({ state, url });
      location.hash = url.includes('#') ? url.slice(url.indexOf('#')) : '';
    },
  };
  view.location = location;
  view.history = history;
  const document = {
    defaultView: view,
    getElementById: (id) => nodes[id] || null,
    createElement: (name) => new Element(name),
  };
  mountSearch(document, location, history);
  return { nodes, view, location, history, calls };
}

test('mount defaults to the static archive with counts of unique published report dates', () => {
  const { nodes } = browser();
  assert.equal(nodes['search-status'].textContent, '공개 보고서 3개 · 항목 4개. 검색어나 태그로 찾아보세요.');
  assert.equal(nodes['search-results'].hidden, true);
  assert.equal(nodes['date-archive'].hidden, false);
  assert.equal(nodes['search-more'].hidden, true);
});

test('unchanged blur change does not replace the result link during a click', () => {
  const { nodes } = browser();
  nodes['search-query'].value = 'memory';
  nodes['search-form'].dispatch('input');
  const first = nodes['search-results'].children[0];
  assert.ok(first);
  nodes['search-form'].dispatch('change');
  assert.equal(nodes['search-results'].children[0], first);
});

test('explicit report dates count published issues even when some have no indexed items', () => {
  const data = {
    ...fixture(),
    report_dates: ['2026-09-17', '2026-09-16', '2026-09-15', '2026-09-14'],
  };
  const { nodes } = browser(data);
  assert.equal(nodes['search-status'].textContent, '공개 보고서 4개 · 항목 4개. 검색어나 태그로 찾아보세요.');
  assert.equal(nodes['search-status'].dataset.error, 'false');
});

test('published issues with no qualifying items retain the archive and an honest empty-item message', () => {
  const data = {
    version: 1, sections, tags: [], items: [],
    report_dates: ['2026-09-16', '2026-09-15'],
  };
  for (const hash of ['', '#q=anything&section=github&from=2026-09-01&to=2026-09-16']) {
    const { nodes } = browser(data, hash);
    assert.equal(
      nodes['search-status'].textContent,
      '공개 보고서 2개 · 검색 가능한 항목 0개. 날짜별 목록에서 수집 결과를 확인하세요.',
    );
    assert.equal(nodes['search-status'].dataset.error, 'false');
    assert.equal(nodes['date-archive'].hidden, false);
    assert.equal(nodes['search-results'].hidden, true);
    assert.equal(nodes['search-results'].children.length, 0);
    assert.equal(nodes['search-more'].hidden, true);
  }
});

test('explicit report dates reject invalid, duplicate, or missing item dates', () => {
  for (const reportDates of [
    null, '2026-09-16', 3, {},
    [],
    ['2026-09-16', '2026-09-15'],
    ['2026-09-16', '2026-09-15', '2026-09-14', '2026-09-14'],
    ['2026-09-16', '2026-09-15', '2026-09-14', '2026-02-30'],
    ['2026-09-16', '2026-09-15', '2026-09-14', 'not-a-date'],
    ['2026-09-16', '2026-09-15', '2026-09-14', 20260917],
  ]) {
    const { nodes } = browser({ ...fixture(), report_dates: reportDates });
    assert.match(nodes['search-status'].textContent, /오류/);
    assert.equal(nodes['search-status'].dataset.error, 'true');
    assert.equal(nodes['date-archive'].hidden, false);
    assert.equal(nodes['search-results'].children.length, 0);
  }
});

test('empty tag hints survive filter restoration and reset without hiding unknown selected tags', () => {
  const data = { version: 1, sections, tags: [], items: [], report_dates: [] };
  const { nodes, location, view } = browser(data);
  const hint = '첫 보고서가 게시되면 태그가 표시됩니다.';
  assert.equal(nodes['search-tags'].textContent, hint);
  assert.equal(nodes['search-status'].textContent, '아직 공개된 보고서가 없습니다. 첫 보고서가 게시되면 검색할 수 있습니다.');
  assert.equal(nodes['search-status'].dataset.error, 'false');
  location.hash = '#q=anything';
  view.dispatch('hashchange');
  assert.equal(nodes['search-tags'].textContent, hint);
  location.hash = '#tag=unknown';
  view.dispatch('hashchange');
  assert.equal(nodes['search-tags'].querySelectorAll('input:checked')[0].value, 'unknown');
  assert.ok(!nodes['search-tags'].textContent.includes(hint));
  nodes['search-reset'].dispatch('click');
  assert.equal(nodes['search-tags'].textContent, hint);
  assert.equal(nodes['search-status'].dataset.error, 'false');
});

test('status error styling distinguishes failures from empty results and clears after correction', () => {
  for (const { nodes } of [
    browser('{'),
    browser(fixture(), '', ['search-data']),
    browser(fixture(), '#section=unknown'),
    browser(fixture(), '#from=2026-09-17&to=2026-09-16'),
  ]) {
    assert.equal(nodes['search-status'].dataset.error, 'true');
  }
  const { nodes, location, view } = browser(fixture(), '#tag=unknown');
  location.hash = '#q=nonexistent';
  view.dispatch('hashchange');
  assert.equal(nodes['search-status'].dataset.error, 'false');
  location.hash = '#q=agent';
  view.dispatch('hashchange');
  assert.equal(nodes['search-status'].dataset.error, 'false');
  nodes['search-reset'].dispatch('click');
  assert.equal(nodes['search-status'].dataset.error, 'false');
});

test('hash initializes filters and form events replace history without network submission', () => {
  const { nodes, calls } = browser(fixture(), '#tag=memory&section=papers');
  assert.equal(nodes['search-section'].value, 'papers');
  assert.equal(nodes['search-tags'].querySelectorAll('input:checked')[0].value, 'memory');
  assert.equal(nodes['search-results'].hidden, false);
  assert.equal(nodes['date-archive'].hidden, true);
  assert.equal(nodes['search-results'].children.length, 1);
  assert.match(nodes['search-status'].textContent, /1.*최신순/);
  nodes['search-query'].value = 'agent';
  nodes['search-form'].dispatch('input', { target: nodes['search-query'] });
  assert.equal(parseFilters(calls.at(-1).url.split('#')[1]).q, 'agent');
  assert.ok(calls.at(-1).url.startsWith('/index.html?scoutTheme=dark#'));
  assert.equal(nodes['search-form'].dispatch('submit').defaultPrevented, true);
});

test('hash changes restore filters and reset returns to the untouched static archive', () => {
  const { nodes, view, location } = browser();
  location.hash = '#q=cloud&section=cncf';
  view.dispatch('hashchange');
  assert.equal(nodes['search-query'].value, 'cloud');
  assert.equal(nodes['search-results'].children.length, 1);
  nodes['search-reset'].dispatch('click');
  assert.equal(location.hash, '');
  assert.equal(nodes['search-query'].value, '');
  assert.equal(nodes['search-section'].value, '');
  assert.equal(nodes['search-results'].hidden, true);
  assert.equal(nodes['date-archive'].hidden, false);
});

test('result tag chips add a tag without replacing query, section, dates, or other tags', () => {
  const hash = '#q=memory&section=github&tag=agent&from=2026-09-01&to=2026-09-16';
  const { nodes, location } = browser(fixture(), hash);
  const article = nodes['search-results'].children[0];
  const tagList = article.children.find((child) => child.className === 'tag-list');
  const memory = tagList.children.find((child) => child.dataset.tag === 'memory');
  memory.dispatch('click');
  assert.deepEqual(parseFilters(location.hash), filters({
    q: 'memory', section: 'github', tags: ['agent', 'memory'],
    from: '2026-09-01', to: '2026-09-16',
  }));
  assert.equal(nodes['search-results'].children.length, 1);
});

test('zero matches and zero indexed reports have distinct explicit Korean messages', () => {
  const noMatches = browser(fixture(), '#q=nonexistent').nodes;
  assert.equal(noMatches['search-status'].textContent, '검색 결과가 없습니다. 검색어 또는 필터를 바꿔보세요.');
  assert.equal(noMatches['date-archive'].hidden, true);
  const empty = browser({ version: 1, sections, tags: [], items: [] }, '#q=anything').nodes;
  assert.equal(empty['search-status'].textContent, '아직 공개된 보고서가 없습니다. 첫 보고서가 게시되면 검색할 수 있습니다.');
  assert.equal(empty['date-archive'].hidden, false);
});

test('pagination starts at 50, adds 50, and resets when filters change', () => {
  const data = { version: 1, sections, tags: [], items: [] };
  for (let index = 0; index < 105; index += 1) {
    data.items.push(item('2026-09-16', 'github', index.toString(16), [], 'agent'));
  }
  const { nodes } = browser(data, '#q=agent');
  assert.equal(nodes['search-results'].children.length, 50);
  assert.equal(nodes['search-more'].hidden, false);
  nodes['search-more'].dispatch('click');
  assert.equal(nodes['search-results'].children.length, 100);
  nodes['search-more'].dispatch('click');
  assert.equal(nodes['search-results'].children.length, 105);
  assert.equal(nodes['search-more'].hidden, true);
  nodes['search-query'].value = 'AGENT';
  nodes['search-form'].dispatch('input', { target: nodes['search-query'] });
  assert.equal(nodes['search-results'].children.length, 50);
});

test('invalid hash filters remain visible, show an error, and cannot silently broaden', () => {
  const { nodes, location } = browser(fixture(), '#section=unknown&tag=bad&from=not-a-date');
  assert.match(nodes['search-status'].textContent, /오류/);
  assert.equal(nodes['search-section'].value, 'unknown');
  assert.equal(nodes['search-from'].value, 'not-a-date');
  assert.equal(nodes['search-tags'].querySelectorAll('input:checked')[0].value, 'bad');
  assert.equal(nodes['search-results'].children.length, 0);
  nodes['search-query'].value = 'agent';
  nodes['search-form'].dispatch('input', { target: nodes['search-query'] });
  assert.equal(parseFilters(location.hash).from, 'not-a-date');
  assert.match(nodes['search-status'].textContent, /오류/);
});

test('reversed date filters show an error and no results', () => {
  const { nodes } = browser(fixture(), '#from=2026-09-17&to=2026-09-16');
  assert.match(nodes['search-status'].textContent, /시작.*종료|날짜/);
  assert.equal(nodes['search-results'].children.length, 0);
  assert.equal(nodes['search-more'].hidden, true);
});

test('malformed JSON and invalid data explicitly fail while the static archive remains usable', () => {
  for (const data of [
    '{', 'null', '{}', { ...fixture(), version: 2 },
    { ...fixture(), sections: [] }, { ...fixture(), items: [{}] },
    { ...fixture(), tags: [{ id: 'memory', label: {}, aliases: [], count: 1 }] },
  ]) {
    const { nodes } = browser(data, '#q=agent');
    assert.match(nodes['search-status'].textContent, /오류/);
    assert.equal(nodes['date-archive'].hidden, false);
    assert.equal(nodes['search-results'].children.length, 0);
    assert.equal(nodes['search-more'].hidden, true);
  }
});

test('missing or malformed index data cannot submit the form to the network', () => {
  for (const { nodes } of [browser('{'), browser(fixture(), '', ['search-data'])]) {
    assert.match(nodes['search-status'].textContent, /오류/);
    assert.equal(nodes['search-form'].dispatch('submit').defaultPrevented, true);
    assert.equal(nodes['date-archive'].hidden, false);
  }
});

test('every result URL must exactly match the dated local-link contract', () => {
  for (const href of [
    'javascript:alert(1)', 'data:text/html,test', '//example.com/',
    'https://example.com/daily/2026-09-16/index.html#item-github-0000000000000002',
    './daily/2026-09-16/index.html#item-github-0000000000000002\n',
    './daily/2026-09-16/index.html#item-github-invalid',
    './daily/2026-09-16/index.html?redirect=evil#item-github-0000000000000002',
    './daily/2026-02-30/index.html#item-github-0000000000000002',
    './daily/2026-09-15/index.html#item-github-0000000000000002',
  ]) {
    const data = fixture();
    data.items[1].href = href;
    const { nodes } = browser(data, '#q=agent');
    assert.match(nodes['search-status'].textContent, /오류/, href);
    assert.equal(nodes['date-archive'].hidden, false);
    assert.equal(nodes['search-results'].children.length, 0);
  }
});

test('untrusted titles, excerpts, and tag labels are rendered as text nodes only', () => {
  const data = fixture();
  const payload = '<img src=x onerror=alert(1)>';
  data.items[1].title = payload;
  data.items[1].body = `memory ${payload}`;
  data.tags[1].label = payload;
  const { nodes } = browser(data, '#section=github&q=memory');
  const article = nodes['search-results'].children[0];
  assert.equal(article.className, 'search-result');
  const heading = article.children.find((child) => child.tagName === 'H3');
  assert.equal(heading.children[0].textContent, payload);
  assert.equal(heading.children[0].getAttribute('href'), data.items[1].href);
  assert.ok(article.textContent.includes(payload));
});

test('inline script is CommonJS-compatible and has no closing script tag or HTML sinks', () => {
  const source = fs.readFileSync(path.join(__dirname, '../search.js'), 'utf8');
  assert.doesNotMatch(source, /<\/script/i);
  assert.doesNotMatch(source, /\b(?:innerHTML|outerHTML|insertAdjacentHTML|document\.write)\b/);
  assert.doesNotMatch(source, /\b(?:fetch|XMLHttpRequest|localStorage|sessionStorage)\s*[.(]/);
});
