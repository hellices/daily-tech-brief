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
    article_groups: {groups:[{id:'group-a',kind:'group',documents:[1]}], periods:{week:[],month:[]}}
  };
  const before = JSON.stringify(data), grouped = A.forGroups(data);
  assert.deepEqual(grouped.items.map(i=>i.nodes), [[], ['group-a']]);
  assert.equal(grouped.items[1].id, 'b');
  assert.equal(grouped.nodes[0].kind, 'group');
  assert.equal(JSON.stringify(data), before);
  assert.throws(() => A.forGroups({items:[]}), /group/i);
});

test('group adapter rejects invalid indices without changing Array.prototype', () => {
  const before = Object.getOwnPropertyDescriptors(Array.prototype);
  try {
    for (const index of ['__proto__', 'constructor', '0', -1, 2, 0.5, NaN, Infinity, null, [], [0], {}]) {
      const data = {
        items: [{id:'a'}, {id:'b'}],
        article_groups: {groups:[{id:'group-a',kind:'group',documents:[index]}], periods:{week:[],month:[]}}
      };
      assert.throws(() => A.forGroups(data), /Invalid group document index/);
      assert.deepEqual(Object.getOwnPropertyDescriptors(Array.prototype), before);
    }
  } finally {
    // Isolate the regression even when the old implementation appends to the prototype.
    Array.prototype.length = before.length.value;
  }
});

test('three-day current windows include both endpoints and exclude neighboring dates', () => {
  const days = ['2026-10-18', '2026-10-19', '2026-10-21', '2026-10-22'];
  const data = {
    meta:{from:days[0],to:days[3]}, tags:[], reports:[],
    items:days.map(date=>({id:date,identity:date,date,nodes:['g'],section:'papers',tags:[],title:date})),
    nodes:[{id:'g',kind:'group',label:'Group',documents:[0,1,2,3]}], links:[]
  };
  const view=A.query(data,{asOf:'2026-10-21',span:'3',kind:'group'});
  assert.deepEqual(view.range,{from:'2026-10-19',to:'2026-10-21'});
  assert.equal(view.total,2);
  assert.equal(view.rows.length,1);
  assert.equal(view.rows[0].count,2);
  assert.deepEqual(view.rows[0].documents,[1,2]);
  assert.deepEqual(A.evidence(data,view,['g']).map(item=>item.date),['2026-10-21','2026-10-19']);
});

test('three-day current windows never fall back to stale report dates', () => {
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
