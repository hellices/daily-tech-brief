const {test, before, after} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');

let browser;
before(async () => { browser = await chromium.launch({headless: true}); });
after(async () => { if (browser) await browser.close(); });

async function fixture(t) {
  const page = await browser.newPage({viewport: {width: 1360, height: 1000}});
  t.after(() => page.close());
  await page.route(/^https?:/, route => route.abort());
  const template = fs.readFileSync(path.join(__dirname, 'template.html'), 'utf8')
    .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, '')
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

function luminance(color) {
  const match = /^rgba?\(([\d.,\s]+)\)$/.exec(color);
  assert.ok(match, 'Unsupported computed color: ' + color);
  const channels = match[1].split(',').map(Number);
  assert.ok(channels.length === 3 || (channels.length === 4 && channels[3] === 1), 'Expected opaque computed color');
  const linear = channels.slice(0, 3).map(value => {
    const v = value / 255;
    return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  });
  return linear[0] * .2126 + linear[1] * .7152 + linear[2] * .0722;
}

async function assertReadable(page, selector) {
  const values = await page.locator(selector).evaluateAll(elements => elements.map(element => {
    const style = getComputedStyle(element);
    let visible = true;
    for (let node = element; node; node = node.parentElement) {
      const parent = getComputedStyle(node);
      visible = visible && parent.display !== 'none' && parent.visibility !== 'hidden' && Number(parent.opacity) === 1;
    }
    return {color: style.color, background: style.backgroundColor, visible};
  }));
  assert.ok(values.length, 'Missing fixture cells: ' + selector);
  for (const value of values) {
    assert.ok(value.visible, 'Fixture cell must be visible');
    const fg = luminance(value.color), bg = luminance(value.background);
    const ratio = (Math.max(fg, bg) + .05) / (Math.min(fg, bg) + .05);
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
    assert.equal(await page.locator(`#graph [data-node="${pair}"]`).count(), 1);
    assert.equal(await page.locator(`#graph [data-edge-source="parent"][data-edge-target="${pair}"]`).count(), 1);
  }
});
