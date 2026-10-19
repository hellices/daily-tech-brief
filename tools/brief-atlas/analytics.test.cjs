const { test } = require('node:test');
const assert = require('node:assert/strict');
const A = require('./analytics.js');
const data = {
  meta: { from: '2026-10-05', to: '2026-10-18' },
  tags: [{id:'agent'}],
  reports: ['2026-10-05','2026-10-12','2026-10-18'].map(date=>({date,coverage:{papers:'ok',community:'ok'}})),
  items: [
    {id:'a1',identity:'a',date:'2026-10-05',section:'papers',tags:['agent'],nodes:['p'],title:'First'},
    {id:'a2',identity:'a',date:'2026-10-12',section:'papers',tags:['agent'],nodes:['p','q'],title:'Again'},
    {id:'b',identity:'b',date:'2026-10-18',section:'community',tags:[],nodes:['p','repo'],title:'New'},
    {id:'c',identity:'c',date:'2026-10-18',section:'community',tags:[],nodes:[],title:'No extracted terms'}
  ],
  nodes: [
    {id:'p',kind:'phrase',label:'adaptive routing',documents:[0,1,2]},
    {id:'q',kind:'phrase',label:'bounded retrieval',documents:[1]},
    {id:'repo',kind:'project',label:'owner/repo',documents:[2]}
  ],
  links: [{source:'p',target:'q',documents:[1]},{source:'p',target:'repo',documents:[2]}],
  periods: {week:[
    {from:'2026-10-05',to:'2026-10-11',node_counts:{p:1},item_count:1,report_count:1},
    {from:'2026-10-12',to:'2026-10-18',node_counts:{p:2,q:1,repo:1},item_count:3,report_count:2}
  ],month:[{from:'2026-10-01',to:'2026-10-18',node_counts:{p:2,q:1,repo:1},item_count:3,report_count:3}]}
};
const opts={asOf:'2026-10-18',span:'all',kind:'phrase',section:'',tag:''};
test('query uses prebuilt graph nodes, no lexical extraction or topic catalog',()=>{
  assert.deepEqual(A.query(data,opts).rows.map(n=>n.id),['p','q']);
});
test('all sections and unextracted entries stay in the archive denominator',()=>{
  assert.equal(A.query(data,opts).total,3);
  assert.equal(A.query(data,{...opts,section:'community'}).total,2);
  assert.equal(A.query(data,{...opts,section:'papers'}).total,1);
});
test('republication is separated from unique source count',()=>{
  const r=A.query(data,opts); assert.equal(r.rows[0].count,2); assert.equal(r.rows[0].occurrences,3);
});
test('seven-day window and section filter are precise',()=>{
  const r=A.query(data,{...opts,span:'7',section:'papers'});
  assert.deepEqual(r.range,{from:'2026-10-12',to:'2026-10-18'});assert.equal(r.total,1);
});
test('first observation never uses future documents',()=>{
  const r=A.query(data,{...opts,asOf:'2026-10-05'});
  assert.equal(r.rows.length,1);assert.equal(r.rows[0].last,'2026-10-05');
  assert.equal(r.rows[0].count,1);assert.equal(r.rows[0].occurrences,1);
});
test('node kinds remain separate unless a user explicitly enables cross-kind links',()=>{
  const r=A.query(data,opts);
  assert.deepEqual(A.neighbors(data,r,'p',false,1).map(e=>e.node.id),['q']);
  assert.equal(A.neighbors(data,r,'p',true,1).length,2);
});
test('edge evidence is an exact same-entry intersection',()=>{
  const r=A.query(data,opts);assert.deepEqual(A.evidence(data,r,['p','q']).map(i=>i.id),['a2']);
});
test('evidence deduplicates only after matching the selected node',()=>{
  const r=A.query(data,opts);
  assert.equal(A.evidence(data,r,['p']).length,2);
  assert.deepEqual(A.evidence(data,r,['q']).map(i=>i.id),['a2']);
});
test('precomputed whole-archive period counts are reused',()=>{
  const r=A.query(data,opts);
  const guarded={...data,items:new Proxy(data.items,{
    get(){assert.fail('Whole-archive series must not read source items');}
  })};
  assert.deepEqual(A.series(guarded,r,'p','week').map(b=>b.count),[1,2]);
  assert.deepEqual(A.series(guarded,r,'p','month').map(b=>b.count),[2]);
});
test('filtered series recomputes selection without changing the stored graph',()=>{
  const before=JSON.stringify(data);const r=A.query(data,{...opts,section:'papers'});
  assert.deepEqual(A.series(data,r,'p','week').map(b=>b.count),[1,1]);assert.equal(JSON.stringify(data),before);
});
test('historical cell selection updates all query surfaces consistently',()=>{
  const r=A.query(data,{...opts,custom:{from:'2026-10-05',to:'2026-10-11'}});
  assert.equal(r.total,1);assert.equal(A.neighbors(data,r,'p',true,1).length,0);
});
test('invalid dates, unknown filters and reversed ranges raise errors',()=>{
  assert.throws(()=>A.query(data,{...opts,asOf:'2026-02-30'}),/date/i);
  assert.throws(()=>A.query(data,{...opts,kind:'frontier'}),/kind/i);
  assert.throws(()=>A.query(data,{...opts,section:'unknown'}),/section/i);
  assert.throws(()=>A.query(data,{...opts,custom:{from:'2026-10-18',to:'2026-10-05'}}),/range/i);
});
test('clipped historical buckets recalculate expected days and collection failures',()=>{
  const d=structuredClone(data);
  d.reports=Array.from({length:14},(_,i)=>({
    date:new Date(Date.UTC(2026,9,5+i)).toISOString().slice(0,10),
    coverage:{papers:i===13?'partial':'ok',community:'ok'}
  }));
  d.periods.week[1].expected_days=7;d.periods.week[1].partial_slots=1;
  const r=A.query(d,{...opts,asOf:'2026-10-14'});
  const bucket=A.series(d,r,'p','week')[1];
  assert.equal(bucket.to,'2026-10-14');
  assert.equal(bucket.report_count,3);
  assert.equal(bucket.expected_days,3);
  assert.equal(bucket.partial_slots,0);
  d.reports.find(x=>x.date==='2026-10-13').coverage.papers='partial';
  assert.equal(A.series(d,A.query(d,{...opts,asOf:'2026-10-14'}),'p','week')[1].partial_slots,1);
});
test('filtered coverage uses only the selected section',()=>{
  const d=structuredClone(data);
  d.reports[1].coverage.community='unavailable';
  d.reports[2].coverage.papers='partial';
  d.periods.week[1].partial_slots=2;
  const r=A.query(d,{...opts,section:'papers'});
  assert.equal(A.series(d,r,'p','week')[1].partial_slots,1);
});
test('kind changes replace focus from a different node type',()=>{
  const r=A.query(data,{...opts,kind:'project'});
  assert.equal(A.selectFocus(data,r,'p'),'repo');
  assert.equal(A.selectFocus(data,r,'p',{explicit:true}),'repo');
});
test('explicit zero-count selections retain their node and empty evidence',()=>{
  const r=A.query(data,{...opts,custom:{from:'2026-10-05',to:'2026-10-11'}});
  assert.equal(A.selectFocus(data,r,'q',{explicit:true}),'q');
  assert.deepEqual(A.evidence(data,r,['q']),[]);
  assert.equal(A.selectFocus(data,r,'q'),'p');
});
