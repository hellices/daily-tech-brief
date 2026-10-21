const {test} = require('node:test');
const assert = require('node:assert/strict');
const A = require('./analytics.js');

test('today uses Korean midnight independently of browser timezone', () => {
  assert.equal(A.kstDay(new Date('2026-10-20T14:59:59Z')), '2026-10-20');
  assert.equal(A.kstDay(new Date('2026-10-20T15:00:00Z')), '2026-10-21');
  assert.throws(() => A.kstDay(new Date('invalid')), /date/i);
});

test('group adapter preserves source indices and does not mutate the original graph', () => {
  const data = {
    items: [{id:'a', nodes:['old']}, {id:'b', nodes:[]}],
    article_groups: {groups:[{id:'group-a',kind:'group',documents:[0]}], periods:{week:[],month:[]}}
  };
  const before = JSON.stringify(data), grouped = A.forGroups(data);
  assert.deepEqual(grouped.items.map(i=>i.nodes), [['group-a'], []]);
  assert.equal(grouped.items[1].id, 'b');
  assert.equal(grouped.nodes[0].kind, 'group');
  assert.equal(JSON.stringify(data), before);
  assert.throws(() => A.forGroups({items:[]}), /group/i);
});

test('three-day current windows are inclusive and never fall back to stale report dates', () => {
  const data = {
    meta:{from:'2026-10-01',to:'2026-10-18'}, tags:[], reports:[],
    items:[{id:'old',identity:'old',date:'2026-10-18',nodes:['g'],section:'papers',tags:[],title:'old'}],
    nodes:[{id:'g',kind:'group',label:'Group',documents:[0]}], links:[]
  };
  const view=A.query(data,{asOf:'2026-10-21',span:'3',kind:'group'});
  assert.deepEqual(view.range,{from:'2026-10-19',to:'2026-10-21'});
  assert.equal(view.total,0);
  assert.equal(view.rows.length,0);
});
