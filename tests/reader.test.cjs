const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const modulePath = path.join(__dirname, '..', 'reader.js');

function api() {
  assert.ok(fs.existsSync(modulePath), 'Document reader behavior is not implemented');
  return require(modulePath);
}

test('header search preserves a relative local destination and encodes literal query', () => {
  const { searchDestination } = api();
  assert.equal(searchDestination('../../index.html', 'agent memory'), '../../index.html#q=agent+memory');
  assert.equal(searchDestination('./index.html', ''), './index.html#archive-search');
  assert.equal(searchDestination('./index.html', '<img>'), './index.html#q=%3Cimg%3E');
});

test('scroll outline picks the latest visible heading above the sticky boundary', () => {
  const { activeSection } = api();
  const headings = [{ id: 'spotlight', top: -500 }, { id: 'github', top: 80 }, { id: 'papers', top: 600 }];
  assert.equal(activeSection(headings, 120), 'github');
  assert.equal(activeSection([{ id: 'spotlight', top: 500 }], 120), 'spotlight');
  assert.equal(activeSection([], 120), null);
});

test('search filter fragments route to the archive search area while item anchors stay intact', () => {
  const { fragmentTarget } = api();
  assert.equal(fragmentTarget('#q=Gavel'), 'archive-search');
  assert.equal(fragmentTarget('#section=papers&tag=memory'), 'archive-search');
  assert.equal(fragmentTarget('#search-tags'), 'search-tags');
  assert.equal(fragmentTarget('#item-papers-abcdef'), 'item-papers-abcdef');
  assert.equal(fragmentTarget(''), null);
});

test('hamburger disclosure closes on Escape, outside interaction and navigation', () => {
  const { setupNavigationMenu } = api();
  const handlers = new Map();
  const linkHandlers = new Map();
  let focused = false;
  const summary = { focus() { focused = true; } };
  const inside = {};
  const link = { addEventListener(type, handler) { linkHandlers.set(type, handler); } };
  const menu = {
    open: false,
    querySelector() { return summary; },
    querySelectorAll() { return [link]; },
    contains(target) { return target === inside || target === summary; },
  };
  const document = { addEventListener(type, handler) { handlers.set(type, handler); } };
  setupNavigationMenu(menu, document);
  assert.equal(menu.open, false);
  menu.open = true;
  handlers.get('pointerdown')({ target: inside });
  assert.equal(menu.open, true);
  handlers.get('pointerdown')({ target: {} });
  assert.equal(menu.open, false);
  menu.open = true;
  let prevented = false;
  handlers.get('keydown')({ key: 'Escape', preventDefault() { prevented = true; } });
  assert.equal(menu.open, false);
  assert.equal(prevented, true);
  assert.equal(focused, true);
  menu.open = true;
  linkHandlers.get('click')();
  assert.equal(menu.open, false);
});
