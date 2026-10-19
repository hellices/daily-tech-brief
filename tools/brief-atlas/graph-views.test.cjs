const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const V = fs.existsSync(__dirname + '/graph-views.js') ? require('./graph-views.js') : {};
const fixture = () => ({
  nodes: ['a','b','c','d','e','f'].map((id,i)=>({id,label:id,kind:'phrase',count:2,documents:[i]})),
  edges: [
    ['a','b',5],['a','c',5],['b','c',5],
    ['d','e',5],['d','f',5],['e','f',5],['c','d',1]
  ].map(([source,target,count])=>({source,target,count,documents:[0]}))
});
test('graph projections include real non-hub edges rather than only spokes',()=>{
  const m=fixture(); const data={items:[{identity:'one'}],links:m.edges.map(e=>({...e,documents:[0]}))};
  const view={allRows:m.nodes,options:{kind:'phrase'},indices:new Set([0])};
  const model=V.project(data,view,'a',{limit:6,minimum:1,cross:false});
  assert.equal(model.nodes.length,6);
  assert.ok(model.edges.some(e=>e.source==='d'&&e.target==='e'));
});
test('projection never fabricates links or mixes types without permission',()=>{
  const m=fixture();m.nodes[5].kind='project';
  const data={items:[{identity:'one'}],links:m.edges};
  const view={allRows:m.nodes,options:{kind:'phrase'},indices:new Set([0])};
  const model=V.project(data,view,'a',{limit:6,minimum:1,cross:false});
  assert.ok(!model.nodes.some(n=>n.id==='f'));
  assert.ok(model.edges.every(e=>m.edges.some(x=>x.source===e.source&&x.target===e.target)));
});
test('modularity groups densely linked communities rather than node types',()=>{
  const m=fixture(); const groups=V.communities(m);
  assert.equal(groups.get('a'),groups.get('b'));
  assert.equal(groups.get('a'),groups.get('c'));
  assert.equal(groups.get('d'),groups.get('e'));
  assert.equal(groups.get('d'),groups.get('f'));
  assert.notEqual(groups.get('a'),groups.get('d'));
  assert.deepEqual([...V.communities(m)],[...groups]);
});
test('tree uses actual connections once per node without pretending cycles are dependencies',()=>{
  const m=fixture();const tree=V.tree(m,'a',4,5,20);
  assert.equal(tree.nodes[0].id,'a');
  assert.equal(new Set(tree.nodes.map(n=>n.id)).size,tree.nodes.length);
  assert.equal(tree.edges.length,tree.nodes.length-1);
  assert.ok(tree.edges.every(e=>m.edges.some(x=>(x.source===e.source&&x.target===e.target)||(x.target===e.source&&x.source===e.target))));
});
test('adjacency matrix is symmetric and distinguishes self-cells from zero edges',()=>{
  const matrix=V.matrix(fixture(),6);
  const index=id=>matrix.nodes.findIndex(n=>n.id===id);
  assert.equal(matrix.values[index('a')][index('a')],null);
  assert.equal(matrix.values[index('a')][index('b')],5);
  assert.equal(matrix.values[index('b')][index('a')],5);
  assert.equal(matrix.values[index('a')][index('d')],0);
});
test('force and clustered layouts are deterministic, bounded, and preserve input',async()=>{
  const d3=await import('d3');const model=fixture();const before=JSON.stringify(model);
  for(const mode of ['network','cluster']){
    const one=V.position(model,mode,900,580,d3);
    const two=V.position(model,mode,900,580,d3);
    assert.deepEqual(one.nodes.map(n=>[n.x,n.y]),two.nodes.map(n=>[n.x,n.y]));
    assert.ok(one.nodes.every(n=>Number.isFinite(n.x)&&n.x>=45&&n.x<=855&&n.y>=40&&n.y<=540));
    assert.equal(JSON.stringify(model),before);
  }
});
