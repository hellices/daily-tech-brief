(function(root){
  'use strict';
  function project(data,view,focus,{limit=24,minimum=1,cross=false,pair='',keepFocus=false}={}){
    const available=view.allRows.filter(n=>(n.count>0||(keepFocus&&n.id===focus))&&(cross||n.kind===view.options.kind));
    const byId=new Map(available.map(n=>[n.id,n]));
    const edges=data.links.filter(e=>byId.has(e.source)&&byId.has(e.target)).map(e=>{
      const documents=e.documents.filter(i=>view.indices.has(i));
      return {...e,documents,count:new Set(documents.map(i=>data.items[i].identity)).size};
    }).filter(e=>e.count>=minimum);
    const adjacent=new Map(available.map(n=>[n.id,[]]));
    for(const e of edges){
      adjacent.get(e.source).push({id:e.target,count:e.count});
      adjacent.get(e.target).push({id:e.source,count:e.count});
    }
    const selected=new Set(),queue=[...new Set([focus,pair].filter(id=>byId.has(id)))];
    const ranked=[...available].sort((a,b)=>b.count-a.count||a.id.localeCompare(b.id));
    while(selected.size<Math.min(limit,available.length)){
      if(!queue.length){
        if(byId.has(focus))break;
        queue.push(ranked.find(n=>!selected.has(n.id)).id);
      }
      const id=queue.shift();
      if(selected.has(id))continue;
      selected.add(id);
      for(const n of adjacent.get(id).sort((a,b)=>b.count-a.count||a.id.localeCompare(b.id))){
        if(!selected.has(n.id)&&!queue.includes(n.id))queue.push(n.id);
      }
    }
    return {nodes:[...selected].map(id=>({...byId.get(id)})),edges:edges.filter(e=>selected.has(e.source)&&selected.has(e.target)),total:available.length};
  }
  function communities(model){
    const ids=model.nodes.map(n=>n.id).sort(),group=new Map(ids.map(id=>[id,id]));
    const degree=new Map(ids.map(id=>[id,0]));
    const m=model.edges.reduce((sum,e)=>sum+e.count,0);
    for(const e of model.edges){degree.set(e.source,degree.get(e.source)+e.count);degree.set(e.target,degree.get(e.target)+e.count);}
    if(m){
      for(let iteration=0;iteration<ids.length;iteration++){
        const volumes=new Map(),between=new Map();
        for(const id of ids)volumes.set(group.get(id),(volumes.get(group.get(id))||0)+degree.get(id));
        for(const e of model.edges){
          const [a,b]=[group.get(e.source),group.get(e.target)].sort();
          if(a===b)continue;
          if(!between.has(a))between.set(a,new Map());
          between.get(a).set(b,(between.get(a).get(b)||0)+e.count);
        }
        let best=null,gain=1e-10;
        for(const a of [...between.keys()].sort()){
          for(const b of [...between.get(a).keys()].sort()){
            const delta=between.get(a).get(b)/m-volumes.get(a)*volumes.get(b)/(2*m*m);
            if(delta>gain){gain=delta;best=[a,b];}
          }
        }
        if(!best)break;
        for(const id of ids)if(group.get(id)===best[1])group.set(id,best[0]);
      }
    }
    const groups=[...new Set(group.values())].sort((a,b)=>ids.filter(id=>group.get(id)===b).length-ids.filter(id=>group.get(id)===a).length||a.localeCompare(b));
    return new Map(ids.map(id=>[id,groups.indexOf(group.get(id))]));
  }
  function tree(model,focus,maxDepth=3,breadth=5,limit=18,{pair=''}={}){
    if(!model.nodes.length)return {nodes:[],edges:[]};
    const byId=new Map(model.nodes.map(n=>[n.id,n]));
    const start=byId.has(focus)?focus:model.nodes[0].id;
    const nodes=[{...byId.get(start),depth:0}],edges=[],seen=new Set([start]),levels=new Map([[0,1]]);
    for(let i=0;i<nodes.length&&nodes.length<limit;i++){
      const parent=nodes[i];
      if(parent.depth>=maxDepth)continue;
      const other=e=>e.source===parent.id?e.target:e.source;
      const connected=model.edges.filter(e=>e.source===parent.id||e.target===parent.id).sort((a,b)=>
        (parent.id===start?Number(other(b)===pair)-Number(other(a)===pair):0)||
        b.count-a.count||a.source.localeCompare(b.source)||a.target.localeCompare(b.target));
      for(const e of connected){
        const id=e.source===parent.id?e.target:e.source,depth=parent.depth+1;
        if(seen.has(id)||(levels.get(depth)||0)>=breadth||nodes.length>=limit)continue;
        seen.add(id);levels.set(depth,(levels.get(depth)||0)+1);
        nodes.push({...byId.get(id),depth,parent:parent.id});
        edges.push({...e,source:parent.id,target:id});
      }
    }
    return {nodes,edges};
  }
  function matrix(model,limit=12,{focus='',pair=''}={}){
    const groups=communities(model);
    const ranked=[...model.nodes].sort((a,b)=>groups.get(a.id)-groups.get(b.id)||b.count-a.count||a.id.localeCompare(b.id));
    const selected=new Set([focus,pair].filter(id=>ranked.some(n=>n.id===id)).slice(0,limit));
    for(const node of ranked)if(selected.size<limit)selected.add(node.id);
    const nodes=ranked.filter(n=>selected.has(n.id));
    const index=new Map(nodes.map((n,i)=>[n.id,i]));
    const values=nodes.map((_,i)=>nodes.map((__,j)=>i===j?null:0));
    for(const e of model.edges){
      if(index.has(e.source)&&index.has(e.target)){
        values[index.get(e.source)][index.get(e.target)]=e.count;
        values[index.get(e.target)][index.get(e.source)]=e.count;
      }
    }
    return {nodes,values,groups};
  }
  function position(model,mode,width,height,d3){
    const groups=communities(model),groupIds=[...new Set(groups.values())];
    const columns=Math.ceil(Math.sqrt(groupIds.length||1)),rows=Math.ceil(groupIds.length/columns)||1;
    const centers=new Map(groupIds.map((g,i)=>[g,{
      x:80+(i%columns+.5)*(width-160)/columns,
      y:70+(Math.floor(i/columns)+.5)*(height-140)/rows
    }]));
    const nodes=model.nodes.map((n,i)=>{
      const c=mode==='cluster'?centers.get(groups.get(n.id)):{x:width/2,y:height/2};
      return {...n,group:groups.get(n.id),r:11+Math.sqrt(n.count)*3,
        x:c.x+Math.cos(i*2.399)*45,y:c.y+Math.sin(i*2.399)*45};
    });
    const edges=model.edges.map(e=>({...e}));
    const simulation=d3.forceSimulation(nodes).randomSource(d3.randomLcg(.42))
      .force('link',d3.forceLink(edges).id(n=>n.id).distance(mode==='cluster'?68:105).strength(mode==='cluster'?.16:.3))
      .force('charge',d3.forceManyBody().strength(mode==='cluster'?-145:-310))
      .force('collision',d3.forceCollide().radius(n=>n.r+25).iterations(3))
      .force('x',d3.forceX(n=>mode==='cluster'?centers.get(n.group).x:width/2).strength(mode==='cluster'?.18:.045))
      .force('y',d3.forceY(n=>mode==='cluster'?centers.get(n.group).y:height/2).strength(mode==='cluster'?.2:.06))
      .stop();
    for(let i=0;i<280;i++){
      simulation.tick();
      for(const n of nodes){
        n.x=Math.max(65,Math.min(width-65,n.x));
        n.y=Math.max(55,Math.min(height-75,n.y));
      }
    }
    return {nodes,edges,groups};
  }
  const api={project,communities,tree,matrix,position};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  else root.GraphViews=api;
})(globalThis);
