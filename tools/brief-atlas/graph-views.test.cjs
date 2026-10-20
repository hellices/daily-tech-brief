const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const V = fs.existsSync(__dirname + '/graph-views.js') ? require('./graph-views.js') : {};
async function loadRenderer(){
  const d3=await import('d3'),context={GraphViews:V,d3};
  vm.runInNewContext(fs.readFileSync(__dirname+'/graph-renderer.js','utf8'),context);
  return {d3,Renderer:context.AtlasGraphRenderer};
}
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
test('focused exploration never fills spare capacity with unrelated components',()=>{
  const nodes=['a','b','c','d'].map(id=>({id,label:id,kind:'phrase',count:1}));
  const data={items:[{identity:'one'}],links:[
    {source:'a',target:'b',documents:[0]},{source:'c',target:'d',documents:[0]}
  ]};
  const view={allRows:nodes,options:{kind:'phrase'},indices:new Set([0])};
  const focused=V.project(data,view,'a',{limit:24});
  assert.deepEqual(focused.nodes.map(n=>n.id),['a','b']);
  assert.deepEqual(focused.edges.map(e=>[e.source,e.target]),[['a','b']]);
  const overview=V.project(data,view,'',{limit:24});
  assert.equal(overview.nodes.length,4);
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
test('rerooted trees keep the selected edge before desktop and mobile breadth limits',()=>{
  for(const breadth of [3,5]){
    const children=Array.from({length:breadth},(_,i)=>'child-'+i);
    const nodes=['root','parent',...children].map(id=>({id,label:id,count:1,kind:'phrase'}));
    const model={nodes,edges:[{source:'root',target:'parent',count:10},
      ...children.map(id=>({source:'parent',target:id,count:1}))]};
    const pair=children.at(-1);
    assert.ok(V.tree(model,'root',3,breadth,18).nodes.some(n=>n.id===pair));
    const selected=V.tree(model,'parent',3,breadth,18,{pair});
    assert.ok(selected.nodes.some(n=>n.id===pair));
    assert.ok(selected.edges.some(e=>e.source==='parent'&&e.target===pair));
  }
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
test('community grouping accepts opaque IDs containing delimiters',()=>{
  const model={nodes:[{id:'a|b'},{id:'c'},{id:'a'},{id:'b|c'}],
    edges:[{source:'a|b',target:'c',count:2},{source:'a',target:'b|c',count:2}]};
  const groups=V.communities(model);
  assert.equal(groups.get('a|b'),groups.get('c'));
  assert.equal(groups.get('a'),groups.get('b|c'));
  assert.notEqual(groups.get('a'),groups.get('a|b'));
});
test('matrix reserves selected nodes beyond both desktop and mobile limits',()=>{
  const nodes=Array.from({length:16},(_,i)=>({id:'n'+String(i).padStart(2,'0'),count:20-i}));
  const edges=nodes.slice(0,14).flatMap((n,i)=>nodes.slice(i+1,14).map(other=>({source:n.id,target:other.id,count:3})));
  const model={nodes,edges:[...edges,{source:'n14',target:'n15',count:1}]};
  for(const limit of [8,12]){
    const m=V.matrix(model,limit,{focus:'n15',pair:'n14'});
    assert.equal(m.nodes.length,limit);
    assert.ok(m.nodes.some(n=>n.id==='n15'));
    assert.ok(m.nodes.some(n=>n.id==='n14'));
    const a=m.nodes.findIndex(n=>n.id==='n15'),b=m.nodes.findIndex(n=>n.id==='n14');
    assert.equal(m.values[a][b],1);
  }
});
test('projection preserves the selected pair before matrix truncation',()=>{
  const m=fixture();
  const items=Array.from({length:5},(_,i)=>({identity:'source-'+i}));
  const links=m.edges.map(e=>({...e,documents:Array.from({length:e.count},(_,i)=>i)}));
  const view={allRows:m.nodes.map(n=>({...n,count:5})),options:{kind:'phrase'},indices:new Set([0,1,2,3,4])};
  const model=V.project({items,links},view,'d',{limit:2,pair:'f'});
  assert.deepEqual(new Set(model.nodes.map(n=>n.id)),new Set(['d','f']));
  assert.deepEqual(model.edges,[{source:'d',target:'f',count:5,documents:[0,1,2,3,4]}]);
});
test('explicit empty focus stays visible without fabricated links',()=>{
  const m=fixture();m.nodes[0].count=0;
  const data={items:[],links:[]},view={allRows:m.nodes,options:{kind:'phrase'},indices:new Set()};
  const model=V.project(data,view,'a',{limit:2,keepFocus:true});
  assert.ok(model.nodes.some(n=>n.id==='a'&&n.count===0));
  assert.deepEqual(model.edges,[]);
});
test('matrix count labels meet 4.5:1 contrast across the gradient',async()=>{
  const {d3,Renderer}=await loadRenderer();
  const luminance=value=>{
    const c=d3.color(value).rgb();
    const linear=[c.r,c.g,c.b].map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4;});
    return linear[0]*.2126+linear[1]*.7152+linear[2]*.0722;
  };
  for(let count=1;count<=100;count++){
    const model={
      nodes:['a','b','c'].map(id=>({id,label:id,kind:'phrase',count:100})),
      edges:[{source:'a',target:'b',count:100},{source:'a',target:'c',count}]
    };
    const element={innerHTML:'',replaceChildren(){}};
    new Renderer(element).render(model,{mode:'matrix'});
    const cells=[...element.innerHTML.matchAll(/class="matrix-cell[^"]*"[^>]*style="background:([^;]+);color:([^"]+)"/g)];
    assert.equal(cells.length,4);
    for(const [,background,foreground] of cells){
      const a=luminance(background),b=luminance(foreground);
      assert.ok((Math.max(a,b)+.05)/(Math.min(a,b)+.05)>=4.5,`${foreground} on ${background}`);
    }
  }
});
test('matrix column buttons identify every node with escaped labels',async()=>{
  const {Renderer}=await loadRenderer(),model=fixture();
  model.nodes[0].label='Alpha & "Beta" <Gamma>';
  const expected=new Map(model.nodes.map(n=>[n.id,n.label]));
  expected.set('a','Alpha &amp; &quot;Beta&quot; &lt;Gamma&gt;');
  for(const compact of [false,true]){
    const element={innerHTML:'',replaceChildren(){}};
    new Renderer(element).render(model,{mode:'matrix',compact});
    const header=element.innerHTML.match(/<thead>([\s\S]*?)<\/thead>/);
    assert.ok(header);
    const buttons=[...header[1].matchAll(/<button\b([^>]*)>/g)];
    assert.equal(buttons.length,model.nodes.length);
    const labels=new Map(buttons.map(([,attributes])=>{
      const id=attributes.match(/\bdata-node="([^"]*)"/),label=attributes.match(/\baria-label="([^"]*)"/);
      assert.ok(id,'Matrix column is missing its node ID');
      assert.ok(label,'Matrix column is missing its accessible name: '+id[1]);
      return [id[1],label[1]];
    }));
    assert.deepEqual(labels,expected);
  }
});
