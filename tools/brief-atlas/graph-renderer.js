(function(root){
  'use strict';
  const palette=['#4386b6','#329788','#bd8050','#8c76b3','#c16d85','#6f9259','#638eaa','#a18b63'];
  const kindColors={phrase:'#4386b6',project:'#329788',name:'#bd8050'};
  const escape=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const wrap=(text,size=22)=>{
    const lines=[''];
    for(const word of text.split(/\s+/)){
      if((lines.at(-1)+' '+word).length>size&&lines.at(-1))lines.push(word);
      else lines[lines.length-1]+=(lines.at(-1)?' ':'')+word;
    }
    return lines.slice(0,2).map((line,i)=>line.slice(0,size)+(line.length>size||(i===1&&lines.length>2)?'…':''));
  };
  class Renderer{
    constructor(element){this.element=element;this.mode='';this.transform=null;}
    zoomBy(value){if(this.svg&&this.zoom)this.svg.call(this.zoom.scaleBy,value);}
    reset(){if(this.svg&&this.zoom)this.svg.call(this.zoom.transform,d3.zoomIdentity);}
    render(model,{mode='network',focus='',pair='',compact=false}={}){
      const V=root.GraphViews,d3=root.d3;
      const width=compact?620:900,height=compact?590:570;
      this.element.replaceChildren();
      this.svg=null;this.zoom=null;
      if(!model.nodes.length){this.element.innerHTML='<p class="empty">연결 없음</p>';return 0;}
      if(mode==='matrix'){
        const m=V.matrix(model,compact?8:12),max=Math.max(1,...m.values.flat().filter(x=>x!==null));
        this.element.innerHTML=`<div class="adjacency-scroll"><table class="adjacency" aria-label="공동 등장 인접 행렬"><thead><tr><th></th>${m.nodes.map((n,i)=>`<th scope="col"><button data-node="${n.id}" title="${escape(n.label)}"><span>${i+1}</span></button></th>`).join('')}</tr></thead><tbody>${m.nodes.map((n,i)=>`<tr><th scope="row"><button data-node="${n.id}" title="${escape(n.label)}"><span class="matrix-index" style="color:${palette[m.groups.get(n.id)%palette.length]}">${i+1}</span>${escape(n.label)}</button></th>${m.values[i].map((value,j)=>{
          const active=(n.id===focus&&m.nodes[j].id===pair)||(n.id===pair&&m.nodes[j].id===focus);
          return `<td>${value===null?'<span class="self-cell">—</span>':value===0?'<span class="zero-cell">·</span>':`<button class="matrix-cell${active?' selected':''}" data-edge-source="${n.id}" data-edge-target="${m.nodes[j].id}" style="background:${d3.interpolateRgb('#edf4f8','#387caa')(value/max)};color:${value/max>.55?'white':'#35546c'}" aria-label="${escape(n.label)} × ${escape(m.nodes[j].label)}, ${value}건">${value}</button>`}</td>`;
        }).join('')}</tr>`).join('')}</tbody></table></div>`;
        this.mode=mode;this.transform=null;return m.nodes.length;
      }
      const svg=d3.select(this.element).append('svg').attr('viewBox',`0 0 ${width} ${height}`)
        .attr('role','group').attr('aria-labelledby','graph-view-title graph-view-desc');
      svg.append('title').attr('id','graph-view-title').text({network:'공동 등장 네트워크',tree:'공동 등장 탐색 트리',cluster:'공동 등장 클러스터'}[mode]);
      svg.append('desc').attr('id','graph-view-desc').text('항목에서 함께 등장한 노드와 연결. 노드 또는 연결을 선택하면 소식을 표시합니다.');
      const viewport=svg.append('g').attr('class','graph-viewport');
      const zoom=d3.zoom().scaleExtent([.4,4]).on('zoom',e=>{viewport.attr('transform',e.transform);this.transform=e.transform;});
      svg.call(zoom).on('dblclick.zoom',null);
      if(this.mode===mode&&this.transform)svg.call(zoom.transform,this.transform);
      else this.transform=d3.zoomIdentity;
      this.svg=svg;this.zoom=zoom;this.mode=mode;
      let layout;
      if(mode==='tree'){
        const tree=V.tree(model,focus,3,compact?3:5,compact?11:17);
        const deepest=Math.max(0,...tree.nodes.map(n=>n.depth));
        layout={nodes:tree.nodes.map(n=>{
          const level=tree.nodes.filter(x=>x.depth===n.depth),i=level.findIndex(x=>x.id===n.id);
          return {...n,x:(i+1)*width/(level.length+1),y:65+n.depth*(height-130)/Math.max(1,deepest),r:18};
        }),edges:tree.edges,groups:V.communities(model)};
      }else layout=V.position(model,mode,width,height,d3);
      const byId=new Map(layout.nodes.map(n=>[n.id,n]));
      const edgeNode=value=>typeof value==='string'?byId.get(value):value;
      const color=n=>mode==='cluster'?palette[layout.groups.get(n.id)%palette.length]:kindColors[n.kind];
      const regions=viewport.append('g').attr('class','cluster-regions');
      const edgeGroups=viewport.append('g').selectAll('g').data(layout.edges).join('g')
        .attr('class','graph-link').attr('role','button').attr('tabindex',0)
        .attr('data-edge-source',e=>edgeNode(e.source).id).attr('data-edge-target',e=>edgeNode(e.target).id)
        .attr('aria-label',e=>`${edgeNode(e.source).label} × ${edgeNode(e.target).label}, ${e.count}건`);
      edgeGroups.append('path').attr('class','edge-hit').attr('stroke','transparent').attr('stroke-width',15).attr('fill','none');
      edgeGroups.append('path').attr('class','edge-stroke').attr('fill','none')
        .attr('stroke',e=>[edgeNode(e.source).id,edgeNode(e.target).id].includes(focus)&&[edgeNode(e.source).id,edgeNode(e.target).id].includes(pair)?'#355f83':'#bbc8d2')
        .attr('stroke-width',e=>Math.min(3,.8+Math.sqrt(e.count)*.55));
      const nodeGroups=viewport.append('g').selectAll('g').data(layout.nodes).join('g')
        .attr('class','graph-node').attr('data-node',n=>n.id).attr('role','button').attr('tabindex',0)
        .attr('aria-label',n=>`${n.label}, ${n.count}건`);
      nodeGroups.append('title').text(n=>`${n.label} · ${n.count}건`);
      if(mode==='tree'){
        nodeGroups.append('rect').attr('x',compact?-72:-66).attr('y',-25).attr('width',compact?144:132).attr('height',50).attr('rx',7)
          .attr('fill',n=>n.id===focus?'#eef5fa':'white').attr('stroke',color).attr('stroke-width',n=>n.id===focus?2:1.3);
        nodeGroups.each(function(n){
          const labels=wrap(n.label,compact?20:22);
          labels.forEach((text,i)=>d3.select(this).append('text').attr('text-anchor','middle').attr('y',(i-(labels.length-1)/2)*14+4).attr('font-size',compact?12:11).attr('fill','#314658').text(text));
        });
      }else{
        nodeGroups.filter(n=>n.id===focus).append('circle').attr('r',n=>n.r+6).attr('fill','none').attr('stroke',color).attr('stroke-opacity',.3).attr('stroke-width',2);
        nodeGroups.append('circle').attr('r',n=>n.r).attr('fill',color).attr('stroke','white').attr('stroke-width',2);
        nodeGroups.append('text').attr('text-anchor','middle').attr('y',4).attr('fill','white').attr('font-size',11).attr('font-weight',600).text(n=>n.count);
        nodeGroups.each(function(n){
          wrap(n.label,compact?18:23).forEach((text,i)=>d3.select(this).append('text').attr('class','node-label').attr('text-anchor','middle')
            .attr('y',n.r+17+i*14).attr('font-size',compact?13:11.5).attr('font-weight',n.id===focus?650:500)
            .attr('fill','#354a5e').attr('paint-order','stroke').attr('stroke','white').attr('stroke-width',3).attr('stroke-linejoin','round').text(text));
        });
      }
      function draw(){
        const path=e=>{
          const s=edgeNode(e.source),t=edgeNode(e.target);
          if(mode==='tree')return `M${s.x},${s.y+25} C${s.x},${(s.y+t.y)/2} ${t.x},${(s.y+t.y)/2} ${t.x},${t.y-25}`;
          const distance=Math.hypot(t.x-s.x,t.y-s.y)||1,ux=(t.x-s.x)/distance,uy=(t.y-s.y)/distance;
          return `M${s.x+ux*(s.r+2)},${s.y+uy*(s.r+2)} L${t.x-ux*(t.r+2)},${t.y-uy*(t.r+2)}`;
        };
        edgeGroups.selectAll('path').attr('d',path);
        nodeGroups.attr('transform',n=>`translate(${n.x},${n.y})`);
        if(mode==='cluster'){
          const groups=d3.groups(layout.nodes,n=>n.group);
          regions.selectAll('ellipse').data(groups,([id])=>id).join('ellipse')
            .attr('cx',([,ns])=>(d3.min(ns,n=>n.x)+d3.max(ns,n=>n.x))/2)
            .attr('cy',([,ns])=>(d3.min(ns,n=>n.y)+d3.max(ns,n=>n.y))/2+10)
            .attr('rx',([,ns])=>(d3.max(ns,n=>n.x)-d3.min(ns,n=>n.x))/2+55)
            .attr('ry',([,ns])=>(d3.max(ns,n=>n.y)-d3.min(ns,n=>n.y))/2+58)
            .attr('fill',([id])=>palette[id%palette.length]).attr('fill-opacity',.095)
            .attr('stroke',([id])=>palette[id%palette.length]).attr('stroke-opacity',.16);
        }
      }
      nodeGroups.call(d3.drag().clickDistance(4).on('start',function(){d3.select(this).raise();})
        .on('drag',(event,n)=>{n.x=event.x;n.y=event.y;draw();}));
      draw();
      return layout.nodes.length;
    }
  }
  root.AtlasGraphRenderer=Renderer;
})(globalThis);
