const {test, before, after} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');
const {parse} = require('acorn');
const siteRoot = path.resolve(__dirname, '../..');

function headerMarkup(base, active) {
  return fs.readFileSync(path.join(siteRoot, 'site-header.html'), 'utf8')
    .replaceAll('@@BASE@@', base).replace('@@NAVIGATION@@', '')
    .replace('@@ARCHIVE_CURRENT@@', active === 'archive' ? ' aria-current="page"' : '')
    .replace('@@INSIGHTS_CURRENT@@', active === 'insights' ? ' aria-current="page"' : '');
}

let browser;
before(async () => { browser = await chromium.launch({headless: true}); });
after(async () => { if (browser) await browser.close(); });

async function fixture(t) {
  const page = await browser.newPage({viewport: {width: 1360, height: 1000}});
  await page.emulateMedia({reducedMotion: 'reduce'});
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  t.after(async () => { await page.close(); assert.deepEqual(errors, [], 'Unexpected browser error'); });
  await page.route(/^https?:/, route => route.abort());
  const header = headerMarkup('../', 'insights');
  const template = fs.readFileSync(path.join(__dirname, 'template.html'), 'utf8')
    .replace(/<script\b([^>]*)>[\s\S]*?<\/script>/gi,
      (script, attrs) => /\btype=["']application\/json["']/i.test(attrs) ? script : '')
    .replace('@@SITE_STYLE@@', fs.readFileSync(path.join(siteRoot, 'site-theme.css'), 'utf8'))
    .replace('@@SITE_HEADER@@', header)
    .replace('@@STYLE@@', fs.readFileSync(path.join(__dirname, 'style.css'), 'utf8'));
  await page.setContent(template);
  for (const file of ['node_modules/d3/dist/d3.min.js', 'graph-views.js', 'graph-renderer.js']) {
    await page.addScriptTag({content: fs.readFileSync(path.join(__dirname, file), 'utf8')});
  }
  await page.evaluate(() => {
    const model = {
      nodes: ['a', 'b', 'c'].map(id => ({id, label: id, kind: 'phrase', count: 1})),
      edges: [{source: 'a', target: 'b', count: 1}]
    };
    new AtlasGraphRenderer(document.getElementById('graph')).render(model, {mode: 'matrix', focus: 'a'});
    document.getElementById('heatmap').innerHTML = '<tbody><tr><td><button class="no-data">—</button></td></tr></tbody>';
  });
  return page;
}

test('archive and atlas share computed branding and visible entry points at every size', async t => {
  const atlas = await fixture(t);
  const archive = await browser.newPage();
  await archive.emulateMedia({reducedMotion: 'reduce'});
  t.after(() => archive.close());
  await archive.route(/^https?:/, route => route.abort());
  const original = fs.readFileSync(path.join(siteRoot, 'template.html'), 'utf8')
    .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, '')
    .replace('@@SITE_STYLE@@', fs.readFileSync(path.join(siteRoot, 'site-theme.css'), 'utf8'))
    .replace('@@SITE_HEADER@@', headerMarkup('./', 'archive'))
    .replaceAll('@@BASE@@', './').replace('@@CONTENT@@', '<h1>Archive fixture</h1>');
  await archive.setContent(original);
  const styles = page => page.evaluate(() => {
    const css = selector => getComputedStyle(document.querySelector(selector));
    return {
      background: css('body').backgroundColor, text: css('body').color, font: css('body').fontFamily,
      header: css('.site-header').backgroundColor, brand: css('.site-brand').fontSize,
      accent: css('[data-site-link="insights"]').color,
      logo: document.querySelector('.site-brand-mark').outerHTML,
      width: document.querySelector('.site-header-inner').getBoundingClientRect().width
    };
  });
  for (const width of [390, 768, 1360]) {
    for (const page of [atlas, archive]) await page.setViewportSize({width, height: 1000});
    for (const theme of ['light', 'dark']) {
      for (const page of [atlas, archive]) await page.evaluate(theme => document.documentElement.dataset.theme = theme, theme);
      assert.deepEqual(await styles(atlas), await styles(archive));
      for (const page of [atlas, archive]) {
        const entry = page.locator('.header-links [data-site-link="insights"]');
        assert.ok(await entry.isVisible());
        assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
        assert.ok(await entry.evaluate(element => !element.closest('details')));
      }
      assert.equal(await atlas.locator('[data-site-link="insights"]').getAttribute('aria-current'), 'page');
      assert.equal(await archive.locator('[data-site-link="archive"]').getAttribute('aria-current'), 'page');
    }
  }
});

test('explicit theme overrides system preference consistently', async t => {
  const page = await fixture(t);
  const themeScript = fs.readFileSync(path.join(siteRoot, 'site-theme.js'), 'utf8');
  await page.emulateMedia({colorScheme: 'dark'});
  await page.route('https://theme.test/**', route => route.fulfill({body: '<html><body></body></html>', contentType: 'text/html'}));
  await page.goto('https://theme.test/?scoutTheme=light');
  await page.addScriptTag({content: themeScript});
  assert.equal(await page.locator('html').getAttribute('data-theme'), 'light');
  await page.goto('https://theme.test/?scoutTheme=invalid');
  await page.addScriptTag({content: themeScript});
  assert.equal(await page.locator('html').getAttribute('data-theme'), 'dark');
});

test('dark graph surfaces and matrix text retain readable contrast', async t => {
  const page = await fixture(t);
  await page.evaluate(() => {
    document.documentElement.dataset.theme = 'dark';
    const nodes = ['a', 'b', 'c'].map(id => ({id, label: id, kind: 'phrase', count: 1}));
    new AtlasGraphRenderer(document.getElementById('graph')).render({
      nodes, edges: [{source: 'a', target: 'b', count: 1}]
    }, {mode: 'matrix', focus: 'a'});
  });
  for (const selector of ['.matrix-index', '.matrix-cell', '.zero-cell', '.self-cell', '#heatmap .no-data']) {
    await assertReadable(page, selector);
  }
});

function rgba(color) {
  const match = /^rgba?\(([\d.,\s]+)\)$/.exec(color);
  assert.ok(match, 'Unsupported computed color: ' + color);
  const channels = match[1].split(',').map(Number);
  assert.ok(channels.length === 3 || channels.length === 4, 'Expected RGB(A) computed color');
  return channels.length === 3 ? [...channels, 1] : channels;
}

function composite(foreground, background) {
  return foreground.slice(0, 3).map((value, i) => value * foreground[3] + background[i] * (1 - foreground[3]));
}

function luminance(channels) {
  const linear = channels.slice(0, 3).map(value => {
    const v = value / 255;
    return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  });
  return linear[0] * .2126 + linear[1] * .7152 + linear[2] * .0722;
}

function contrast(foreground, background) {
  const fg = luminance(foreground), bg = luminance(background);
  return (Math.max(fg, bg) + .05) / (Math.min(fg, bg) + .05);
}

async function assertReadable(page, selector) {
  const values = await page.locator(selector).evaluateAll(elements => elements.map(element => {
    const style = getComputedStyle(element);
    let visible = true;
    const backgrounds = [];
    for (let node = element; node; node = node.parentElement) {
      const parent = getComputedStyle(node);
      visible = visible && parent.display !== 'none' && parent.visibility !== 'hidden' && Number(parent.opacity) === 1;
      assertSolidBackground(parent);
      backgrounds.unshift(parent.backgroundColor);
    }
    function assertSolidBackground(style) {
      if (style.backgroundImage !== 'none') throw new Error('Contrast fixture requires solid backgrounds');
    }
    return {color: style.color, backgrounds, visible};
  }));
  assert.ok(values.length, 'Missing fixture cells: ' + selector);
  for (const value of values) {
    assert.ok(value.visible, 'Fixture cell must be visible');
    const background = value.backgrounds.reduce((bg, color) => composite(rgba(color), bg), [255, 255, 255]);
    const ratio = contrast(composite(rgba(value.color), background), background);
    assert.ok(ratio >= 4.5, `${selector} contrast ${ratio.toFixed(3)} is below 4.5`);
  }
}

test('empty chart cells meet contrast using rendered CSS on desktop and mobile', async t => {
  const page = await fixture(t);
  for (const width of [1360, 390]) {
    await page.setViewportSize({width, height: 1000});
    for (const selector of ['#graph .zero-cell', '#graph .self-cell', '#heatmap .no-data']) {
      await assertReadable(page, selector);
    }
  }
});

function literalDomIds(source) {
  const ids = [];
  function visit(node) {
    if (!node || typeof node !== 'object') return;
    if (node.type === 'CallExpression' && node.callee.type === 'Identifier' && node.callee.name === '$') {
      const argument = node.arguments[0];
      if (argument?.type === 'Literal' && typeof argument.value === 'string') ids.push(argument.value);
      if (argument?.type === 'TemplateLiteral' && argument.expressions.length === 0) ids.push(argument.quasis[0].value.cooked);
    }
    for (const value of Object.values(node)) {
      if (Array.isArray(value)) value.forEach(visit);
      else if (value && typeof value === 'object') visit(value);
    }
  }
  visit(parse(source, {ecmaVersion: 'latest'}));
  return ids;
}

function assertDomTargets(source, targets) {
  for (const id of literalDomIds(source)) assert.ok(targets.has(id), 'Orphaned DOM reference: ' + id);
}

test('layout controls expose a named accessible group', async t => {
  const page = await fixture(t);
  const group = page.getByRole('group', {name: '그래프 보기', exact: true});
  assert.equal(await group.count(), 1);
  assert.equal(await group.getByRole('button').count(), 4);
});

test('literal UI DOM calls resolve against the actual template', async t => {
  const page = await fixture(t);
  const targets = new Set(await page.locator('[id]').evaluateAll(elements => elements.map(e => e.id)));
  assertDomTargets(fs.readFileSync(path.join(__dirname, 'ui.js'), 'utf8'), targets);
});

test('DOM guard parses whitespace, comments, escaping and static template literals', () => {
  for (const source of ["$('missing-target')", '$ ("missing-target")', "$\n('missing-target')",
    "$ /* comment */ ('missing-target')", "$('missing\\u002dtarget')", '$(`missing-target`)']) {
    assert.throws(() => assertDomTargets(source, new Set(['graph'])), /Orphaned DOM reference: missing-target/);
  }
});

test('DOM guard ignores comments and quoted text that are not calls', () => {
  assert.deepEqual(literalDomIds("// $('not-a-call')\nconst text = \"$('not-a-call')\";\n$('graph')"), ['graph']);
});

test('matrix row indices meet text contrast for every community color', async t => {
  const page = await fixture(t);
  for (const compact of [false, true]) {
    await page.setViewportSize({width: compact ? 390 : 1360, height: 1000});
    await page.evaluate(compact => {
      const nodes = Array.from({length: 8}, (_, i) => ({id: 'g' + i, label: 'Group ' + i, kind: 'phrase', count: 1}));
      new AtlasGraphRenderer(document.getElementById('graph')).render({nodes, edges: []}, {mode: 'matrix', compact});
    }, compact);
    assert.equal(await page.locator('.matrix-index').count(), 8);
    await assertReadable(page, '.matrix-index');
  }
});

async function assertEdgeContrast(page, mode) {
  const samples = await page.evaluate(() => {
    const background = getComputedStyle(document.getElementById('graph')).backgroundColor;
    const regions = [...document.querySelectorAll('.cluster-regions ellipse')];
    function effectiveOpacity(element) {
      let opacity = 1;
      for (let node = element; node; node = node.parentElement) {
        const style = getComputedStyle(node);
        if (style.display === 'none' || style.visibility === 'hidden') return 0;
        opacity *= Number(style.opacity);
      }
      return opacity;
    }
    return [...document.querySelectorAll('.edge-stroke')].flatMap(path =>
      [.2, .5, .8].map(fraction => {
        const local = path.getPointAtLength(path.getTotalLength() * fraction);
        const screen = new DOMPoint(local.x, local.y).matrixTransform(path.getScreenCTM());
        const layers = regions.filter(region => {
          const point = screen.matrixTransform(region.getScreenCTM().inverse());
          return region.isPointInFill(point);
        }).map(region => ({color: getComputedStyle(region).fill, opacity: Number(getComputedStyle(region).fillOpacity)}));
        return {background, stroke: getComputedStyle(path).stroke,
          opacity: Number(getComputedStyle(path).strokeOpacity) * effectiveOpacity(path), layers};
      }));
  });
  assert.ok(samples.length);
  if (mode === 'cluster') assert.ok(samples.some(sample => sample.layers.length > 0));
  for (const sample of samples) {
    let background = rgba(sample.background).slice(0, 3);
    for (const layer of sample.layers) {
      const color = rgba(layer.color); color[3] *= layer.opacity;
      background = composite(color, background);
    }
    const stroke = rgba(sample.stroke); stroke[3] *= sample.opacity;
    const ratio = contrast(composite(stroke, background), background);
    assert.ok(ratio >= 3, `${mode} edge contrast ${ratio.toFixed(3)} is below 3`);
  }
}

test('unselected edges meet non-text contrast over the chart and rendered cluster fills', async t => {
  const page = await fixture(t);
  for (const mode of ['network', 'tree', 'cluster']) {
    await page.evaluate(mode => {
      const nodes = Array.from({length: 16}, (_, i) => ({id: 'n' + i, label: 'Node ' + i, kind: 'phrase', count: 1}));
      const edges = Array.from({length: 8}, (_, i) => ({source: 'n' + 2 * i, target: 'n' + (2 * i + 1), count: 1}));
      new AtlasGraphRenderer(document.getElementById('graph')).render({nodes, edges}, {mode, focus: 'n0'});
    }, mode);
    await assertEdgeContrast(page, mode);
  }
});

test('edge contrast guard rejects opacity overrides on paths and ancestors', async t => {
  const page = await fixture(t);
  await page.evaluate(() => {
    const nodes = ['a', 'b'].map(id => ({id, label: id, kind: 'phrase', count: 1}));
    new AtlasGraphRenderer(document.getElementById('graph')).render({
      nodes, edges: [{source: 'a', target: 'b', count: 1}]
    }, {mode: 'network', focus: 'a'});
  });
  await assertEdgeContrast(page, 'network');
  for (const selector of ['.edge-stroke', '.graph-link', '.graph-viewport', '#graph']) {
    for (const opacity of ['0', '0.05']) {
      await page.locator(selector).first().evaluate((element, value) => { element.style.opacity = value; }, opacity);
      await assert.rejects(assertEdgeContrast(page, 'network'), /edge contrast .* is below 3/);
      await page.locator(selector).first().evaluate(element => element.style.removeProperty('opacity'));
      await assertEdgeContrast(page, 'network');
    }
  }
});

async function populatedFixture(t, nodeCount = 2, includeProject = false, baselineNodes = null) {
  const page = await fixture(t);
  await page.evaluate(({nodeCount, includeProject, baselineNodes}) => {
    const nodeIds = ['a', 'b', ...Array.from({length: nodeCount - 2}, (_, i) => 'node-' + i)];
    if (includeProject) nodeIds.push('project-demo');
    const dates = ['2026-10-18', '2026-10-19'];
    const items = Array.from({length: 16}, (_, i) => ({
      id: 'item-' + i, identity: 'source-' + i, date: dates[i < 8 ? 0 : 1], section: 'community',
      title: 'Source ' + i, tags: ['alpha'], nodes: nodeIds, matches: {}, href: '#item-' + i, url: 'https://example.org/' + i
    }));
    if (baselineNodes) {
      for (let i = 0; i < 3; i++) items.push({
        id: 'prior-' + i, identity: 'prior-source-' + i, date: '2026-10-' + (7 + i).toString().padStart(2, '0'),
        section: 'community', title: 'Prior source ' + i, tags: ['alpha'],
        nodes: baselineNodes, matches: {}, href: '#prior-' + i, url: 'https://example.org/prior/' + i
      });
    }
    const reportDates = baselineNodes ? Array.from({length: 14}, (_, i) => new Date(Date.UTC(2026, 9, 6 + i)).toISOString().slice(0, 10)) : dates;
    const bucket = (from, to, count, reports, days) => ({
      from, to, node_counts: Object.fromEntries(nodeIds.map(id => [id, count])), item_count: count, report_count: reports, expected_days: days, partial_slots: 0
    });
    const data = {
      meta: {from: reportDates[0], to: dates[1]}, tags: [{id: 'alpha', label: 'Alpha'}],
      reports: reportDates.map(date => ({date, coverage: {github: 'ok', papers: 'ok', community: 'ok', cncf: 'ok'}})),
      items, details: items.map(() => ({body: '', summary: '', topics: []})),
      nodes: nodeIds.map(id => ({id, kind: id === 'project-demo' ? 'project' : 'phrase', label: id, documents: items.flatMap((item, i) => item.nodes.includes(id) ? [i] : [])})),
      links: nodeIds.flatMap((source, i) => nodeIds.slice(i + 1).map(target => ({
        source, target, documents: items.flatMap((item, index) => item.nodes.includes(source) && item.nodes.includes(target) ? [index] : [])
      }))),
      periods: {
        week: [bucket('2026-10-12', dates[0], 8, 1, 7), bucket(dates[1], dates[1], 8, 1, 1)],
        month: [bucket('2026-10-01', dates[1], 16, 2, 19)]
      }
    };
    document.getElementById('snapshot').textContent = JSON.stringify(data);
  }, {nodeCount, includeProject, baselineNodes});
  for (const file of ['analytics.js', 'ui.js']) {
    await page.addScriptTag({content: fs.readFileSync(path.join(__dirname, file), 'utf8')});
  }
  return page;
}

test('default discovery prioritizes repeated share gains rather than lifetime frequency', async t => {
  const page = await populatedFixture(t, 2, false, ['a']);
  assert.equal(await page.locator('#span').inputValue(), '7');
  assert.equal(await page.locator('#ordering').inputValue(), 'rising');
  assert.equal(await page.locator('#detail-title').innerText(), 'b');
  assert.equal(await page.locator('#node-list [data-node="a"]').count(), 0);
  assert.equal(await page.locator('#node-list [data-node="b"]').count(), 1);
  assert.equal(await page.locator('#heatmap .change-delta').first().innerText(), '+100.0');
  assert.equal(await page.locator('#evidence-count').innerText(), '16건');
  await page.locator('#ordering').selectOption('count');
  assert.equal(await page.locator('#node-list [data-node="a"]').count(), 1);
});

test('no rising observations does not fill the default graph with unrelated entries', async t => {
  const page = await populatedFixture(t, 2, false, ['a', 'b']);
  assert.equal(await page.locator('#graph .graph-node').count(), 0);
  assert.equal(await page.locator('#evidence-count').innerText(), '0건');
  assert.ok((await page.locator('#heatmap').innerText()).includes('반복 증가 항목 없음'));
  await page.locator('#inventory').click();
  assert.equal(await page.locator('#evidence-count').innerText(), '16건');
});

async function assertNeutralCopy(page) {
  const texts = await page.evaluate(() => [
    document.body.innerText,
    ...[...document.querySelectorAll('svg text, svg title, svg desc')].map(element => element.textContent),
    ...[...document.querySelectorAll('[aria-label], [title], [placeholder], [alt]')]
      .flatMap(element => ['aria-label', 'title', 'placeholder', 'alt'].map(name => element.getAttribute(name) || ''))
  ]);
  const forbidden = ['MODEL CALLS', 'STATIC GRAPH', 'MATERIALIZED', '반복 포착', '다음 질문',
    '해 보세요', '해보세요', '같은 입력', '준비할지', '자동 추출된', '포착'];
  for (const text of texts) {
    const normalized = text.normalize('NFKC').replace(/\s+/gu, ' ').trim();
    for (const phrase of forbidden) assert.ok(!normalized.includes(phrase), 'Disallowed interface copy: ' + phrase);
  }
}

test('initialized UI and user-facing labels remain free of generated guidance', async t => {
  const page = await populatedFixture(t);
  for (const layout of ['network', 'tree', 'matrix', 'cluster']) {
    await page.locator(`[data-layout="${layout}"]`).click();
    await assertNeutralCopy(page);
  }
});

test('copy guard rejects runtime-concatenated text and label attributes', async t => {
  const page = await populatedFixture(t);
  for (const target of ['text', 'aria-label', 'title', 'placeholder']) {
    await page.evaluate(target => {
      const element = document.createElement(target === 'text' ? 'p' : 'input');
      element.id = 'copy-regression';
      const label = '다음 ' + '질문';
      if (target === 'text') element.textContent = label;
      else element.setAttribute(target, label);
      document.querySelector('main').append(element);
    }, target);
    await assert.rejects(assertNeutralCopy(page), /Disallowed interface copy: 다음 질문/);
    await page.locator('#copy-regression').evaluate(element => element.remove());
  }
});

test('selecting a new edge resets evidence pagination while preserving its pair', async t => {
  const page = await populatedFixture(t);
  await page.locator('#inventory').click();
  await page.locator('[data-layout="matrix"]').click();
  assert.equal(await page.locator('.evidence').count(), 5);
  await page.locator('#more-evidence').click();
  assert.equal(await page.locator('.evidence').count(), 15);
  await page.locator('.matrix-cell').first().click();
  assert.equal(await page.locator('#detail-title').innerText(), 'a × b');
  assert.equal(await page.locator('#evidence-count').innerText(), '16건');
  assert.equal(await page.locator('.evidence').count(), 5);
});

test('tag and node-type filters preserve the heatmap-selected date interval', async t => {
  const page = await populatedFixture(t, 2, true);
  for (const [control, value] of [['tag', 'alpha'], ['kind', 'project']]) {
    await page.locator('#reset').click();
    await page.locator('#heatmap [data-cell="a"][data-from="2026-10-12"]').click();
    assert.equal(await page.locator('#evidence-count').innerText(), '8건');
    await page.locator('#' + control).selectOption(value);
    assert.equal(await page.locator('#span').inputValue(), 'custom');
    assert.equal(await page.locator('#period-label').innerText(), '2026-10-12 — 2026-10-18');
    assert.equal(await page.locator('#evidence-count').innerText(), '8건');
    assert.ok(await page.locator('.evidence-meta').evaluateAll(elements => elements.every(e => e.textContent.startsWith('2026-10-18'))));
    if (control === 'kind') assert.equal(await page.locator('#detail-kind').innerText(), '프로젝트');
  }
  await page.locator('#span').selectOption('all');
  assert.equal(await page.locator('#period-label').innerText(), '2026-10-18 — 2026-10-19');
  assert.equal(await page.locator('#evidence-count').innerText(), '16건');
});

test('keyboard clearing a pair moves focus to a visible source panel', async t => {
  const page = await populatedFixture(t);
  for (const width of [1360, 390]) {
    await page.setViewportSize({width, height: 1000});
    await page.locator('[data-layout="matrix"]').click();
    for (const key of ['Enter', 'Space']) {
      await page.locator('.matrix-cell').first().click();
      await page.locator('#clear-pair').focus();
      await page.locator('#clear-pair').press(key);
      assert.ok(await page.locator('#clear-pair').isHidden());
      assert.equal(await page.evaluate(() => document.activeElement.id), 'detail-panel');
      assert.ok(await page.locator('#detail-panel').isVisible());
    }
  }
});

test('keyboard pagination retains focus when its last-page button disappears', async t => {
  const page = await populatedFixture(t, 30);
  await page.locator('#inventory').click();
  await page.locator('#more-evidence').focus();
  await page.locator('#more-evidence').press('Enter');
  await page.locator('#more-evidence').press('Space');
  assert.ok(await page.locator('#more-evidence').isHidden());
  assert.equal(await page.evaluate(() => document.activeElement.id), 'detail-panel');
  await page.locator('#more-nodes').focus();
  await page.locator('#more-nodes').press('Enter');
  assert.ok(await page.locator('#more-nodes').isHidden());
  assert.equal(await page.evaluate(() => document.activeElement.id), 'node-search');
});

test('fit view recenters dragged graph bounds including labels on desktop and mobile', async t => {
  const page = await fixture(t);
  for (const width of [1360, 390]) {
    await page.setViewportSize({width, height: 1000});
    for (const mode of ['network', 'tree', 'cluster']) {
      await page.evaluate(({mode, compact}) => {
        const nodes = Array.from({length: 6}, (_, i) => ({
          id: 'fit-' + i, label: 'Readable graph node ' + i, kind: 'phrase', count: 1
        }));
        const edges = nodes.slice(1).map((node, i) => ({source: nodes[i].id, target: node.id, count: 1}));
        globalThis.fitTestRenderer = new AtlasGraphRenderer(document.getElementById('graph'));
        fitTestRenderer.render({nodes, edges}, {mode, focus: 'fit-0', compact});
        fitTestRenderer.zoomBy(.5);
      }, {mode, compact: width < 500});
      const node = page.locator('#graph .graph-node[data-node="fit-0"]');
      for (let i = 0; i < 3; i++) {
        await page.evaluate(() => {
          const renderer = fitTestRenderer;
          const point = renderer.svg.select('[data-node="fit-0"]').datum();
          const box = renderer.svg.node().viewBox.baseVal;
          const scale = d3.zoomTransform(renderer.svg.node()).k;
          renderer.svg.call(renderer.zoom.transform,
            d3.zoomIdentity.translate(box.width / 2 - point.x * scale, box.height / 2 - point.y * scale).scale(scale));
        });
        const shape = node.locator(mode === 'tree' ? 'rect' : 'circle').last();
        const from = await shape.boundingBox(), svg = await page.locator('#graph svg').boundingBox();
        await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2);
        await page.mouse.down();
        await page.mouse.move(svg.x + svg.width - 12, svg.y + svg.height - 15, {steps: 6});
        await page.mouse.up();
      }
      assert.ok(await page.evaluate(() => {
        const svg = fitTestRenderer.svg.node();
        const box = svg.querySelector('.graph-viewport').getBBox();
        return box.x + box.width > svg.viewBox.baseVal.width;
      }), 'Fixture must drag content beyond the original viewBox');
      await page.evaluate(() => fitTestRenderer.reset());
      const fitted = await page.evaluate(() => {
        const svg = fitTestRenderer.svg.node(), outer = svg.getBoundingClientRect();
        const inner = svg.querySelector('.graph-viewport').getBoundingClientRect();
        return inner.left >= outer.left - 1 && inner.top >= outer.top - 1 &&
          inner.right <= outer.right + 1 && inner.bottom <= outer.bottom + 1;
      });
      assert.ok(fitted, `${mode} must fit its dragged content and labels at ${width}px`);
    }
  }
});

test('contrast guard rejects a more-specific stylesheet override', async t => {
  const page = await fixture(t);
  await page.addStyleTag({content: '#graph .adjacency .zero-cell { color: #ffffff; }'});
  await assert.rejects(assertReadable(page, '#graph .zero-cell'), /contrast .*below 4\.5/);
});

test('contrast guard rejects inline overrides', async t => {
  const page = await fixture(t);
  await page.locator('#graph .self-cell').first().evaluate(element => { element.style.color = '#ffffff'; });
  await assert.rejects(assertReadable(page, '#graph .self-cell'), /contrast .*below 4\.5/);
});

test('contrast guard resolves inherited custom-property changes', async t => {
  const page = await fixture(t);
  await page.evaluate(() => document.documentElement.style.setProperty('--muted', '#ffffff'));
  await assert.rejects(assertReadable(page, '#heatmap .no-data'), /contrast .*below 4\.5/);
});

test('tree renderer keeps the selected connection after rerooting on desktop and mobile', async t => {
  const page = await fixture(t);
  for (const compact of [false, true]) {
    await page.setViewportSize({width: compact ? 390 : 1360, height: 1000});
    const pair = await page.evaluate(compact => {
      const children = Array.from({length: compact ? 3 : 5}, (_, i) => 'child-' + i);
      const model = {
        nodes: ['root', 'parent', ...children].map(id => ({id, label: id, kind: 'phrase', count: 1})),
        edges: [{source: 'root', target: 'parent', count: 10},
          ...children.map(id => ({source: 'parent', target: id, count: 1}))]
      };
      const pair = children.at(-1);
      new AtlasGraphRenderer(document.getElementById('graph')).render(model, {
        mode: 'tree', focus: 'parent', pair, compact
      });
      return pair;
    }, compact);
    const node = page.locator(`#graph [data-node="${pair}"]`);
    const edge = page.locator(`#graph [data-edge-source="parent"][data-edge-target="${pair}"]`);
    const assertDrawn = async locator => {
      assert.equal(await locator.count(), 1);
      assert.ok(await locator.isVisible(), 'Selected graph element must be visible');
      assert.ok(await locator.evaluate(element => {
        for (let n = element; n; n = n.parentElement) {
          const style = getComputedStyle(n);
          if (Number(style.opacity) === 0 || style.display === 'none' || style.visibility === 'hidden') return false;
        }
        return true;
      }), 'Selected graph element must not be transparent');
    };
    await assertDrawn(node);
    await assertDrawn(edge);
    for (const locator of [node, edge]) {
      await locator.evaluate(element => { element.style.opacity = '0'; });
      await assert.rejects(assertDrawn(locator), /must not be transparent/);
      await locator.evaluate(element => element.style.removeProperty('opacity'));
    }
  }
});
