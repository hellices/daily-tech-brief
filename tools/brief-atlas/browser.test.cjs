const {test, before, after} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');
const {parse} = require('acorn');

let browser;
before(async () => { browser = await chromium.launch({headless: true}); });
after(async () => { if (browser) await browser.close(); });

async function fixture(t) {
  const page = await browser.newPage({viewport: {width: 1360, height: 1000}});
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  t.after(async () => { await page.close(); assert.deepEqual(errors, [], 'Unexpected browser error'); });
  await page.route(/^https?:/, route => route.abort());
  const template = fs.readFileSync(path.join(__dirname, 'template.html'), 'utf8')
    .replace(/<script\b([^>]*)>[\s\S]*?<\/script>/gi,
      (script, attrs) => /\btype=["']application\/json["']/i.test(attrs) ? script : '')
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

test('unselected edges meet non-text contrast over the chart and rendered cluster fills', async t => {
  const page = await fixture(t);
  for (const mode of ['network', 'tree', 'cluster']) {
    await page.evaluate(mode => {
      const nodes = Array.from({length: 16}, (_, i) => ({id: 'n' + i, label: 'Node ' + i, kind: 'phrase', count: 1}));
      const edges = Array.from({length: 8}, (_, i) => ({source: 'n' + 2 * i, target: 'n' + (2 * i + 1), count: 1}));
      new AtlasGraphRenderer(document.getElementById('graph')).render({nodes, edges}, {mode, focus: 'n0'});
    }, mode);
    const samples = await page.evaluate(() => {
      const background = getComputedStyle(document.getElementById('graph')).backgroundColor;
      const regions = [...document.querySelectorAll('.cluster-regions ellipse')];
      return [...document.querySelectorAll('.edge-stroke')].flatMap(path =>
        [.2, .5, .8].map(fraction => {
          const local = path.getPointAtLength(path.getTotalLength() * fraction);
          const screen = new DOMPoint(local.x, local.y).matrixTransform(path.getScreenCTM());
          const layers = regions.filter(region => {
            const point = screen.matrixTransform(region.getScreenCTM().inverse());
            return region.isPointInFill(point);
          }).map(region => ({color: getComputedStyle(region).fill, opacity: Number(getComputedStyle(region).fillOpacity)}));
          return {background, stroke: getComputedStyle(path).stroke, opacity: Number(getComputedStyle(path).strokeOpacity), layers};
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
});

test('selecting a new edge resets evidence pagination while preserving its pair', async t => {
  const page = await fixture(t);
  await page.evaluate(() => {
    const dates = ['2026-10-18', '2026-10-19'];
    const items = Array.from({length: 16}, (_, i) => ({
      id: 'item-' + i, identity: 'source-' + i, date: dates[i < 8 ? 0 : 1], section: 'community',
      title: 'Source ' + i, tags: [], nodes: ['a', 'b'], matches: {}, href: '#item-' + i, url: 'https://example.org/' + i
    }));
    const bucket = (from, to, count, reports, days) => ({
      from, to, node_counts: {a: count, b: count}, item_count: count, report_count: reports, expected_days: days, partial_slots: 0
    });
    const data = {
      meta: {from: dates[0], to: dates[1]}, tags: [],
      reports: dates.map(date => ({date, coverage: {github: 'ok', papers: 'ok', community: 'ok', cncf: 'ok'}})),
      items, details: items.map(() => ({body: '', summary: '', topics: []})),
      nodes: ['a', 'b'].map(id => ({id, kind: 'phrase', label: id, documents: items.map((_, i) => i)})),
      links: [{source: 'a', target: 'b', documents: items.map((_, i) => i)}],
      periods: {
        week: [bucket('2026-10-12', dates[0], 8, 1, 7), bucket(dates[1], dates[1], 8, 1, 1)],
        month: [bucket('2026-10-01', dates[1], 16, 2, 19)]
      }
    };
    document.getElementById('snapshot').textContent = JSON.stringify(data);
  });
  for (const file of ['analytics.js', 'ui.js']) {
    await page.addScriptTag({content: fs.readFileSync(path.join(__dirname, file), 'utf8')});
  }
  await page.locator('#inventory').click();
  await page.locator('#more-evidence').click();
  assert.equal(await page.locator('.evidence').count(), 15);
  await page.locator('[data-layout="matrix"]').click();
  await page.locator('.matrix-cell').first().click();
  assert.equal(await page.locator('#detail-title').innerText(), 'a × b');
  assert.equal(await page.locator('#evidence-count').innerText(), '16건');
  assert.equal(await page.locator('.evidence').count(), 5);
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
