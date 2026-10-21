const {test,before,after}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {parse}=require('acorn');
const {chromium}=require('playwright');
const siteRoot=path.resolve(__dirname,'../..');
let browser;
before(async()=>{browser=await chromium.launch({headless:true});});
after(async()=>{if(browser)await browser.close();});

function header(base,active){
  return fs.readFileSync(path.join(siteRoot,'site-header.html'),'utf8')
    .replaceAll('@@BASE@@',base).replace('@@NAVIGATION@@','')
    .replace('@@ARCHIVE_CURRENT@@',active==='archive'?' aria-current="page"':'')
    .replace('@@INSIGHTS_CURRENT@@',active==='insights'?' aria-current="page"':'');
}
async function shell(t){
  const page=await browser.newPage({viewport:{width:1360,height:1000}});
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  t.after(async()=>{await page.close();assert.deepEqual(errors,[]);});
  await page.route(/^https?:/,route=>route.abort());
  await page.emulateMedia({reducedMotion:'reduce'});
  await page.clock.setFixedTime(new Date('2026-10-19T03:00:00Z'));
  const template=fs.readFileSync(path.join(__dirname,'template.html'),'utf8')
    .replace(/<script\b([^>]*)>[\s\S]*?<\/script>/gi,(text,attrs)=>/\btype=["']application\/json["']/i.test(attrs)?text:'')
    .replace('@@SITE_STYLE@@',fs.readFileSync(path.join(siteRoot,'site-theme.css'),'utf8'))
    .replace('@@STYLE@@',fs.readFileSync(path.join(__dirname,'style.css'),'utf8'))
    .replace('@@SITE_HEADER@@',header('../','insights'));
  await page.setContent(template);
  return page;
}
async function populated(t,{groupCount=2,firstSize=4,previousSize=1,family}={}){
  const page=await shell(t);
  await page.evaluate(({groupCount,firstSize,previousSize,family})=>{
    const items=[],groups=[],details=[];
    const add=(id,date,section,group)=>{
      const index=items.length;
      items.push({id,identity:id,date,section,title:'Source '+id,tags:['memory'],nodes:[],href:'#'+id,url:'https://example.org/'+id});
      details.push({summary:'Source summary '+id,body:'Original source '+id,topics:['procedural memory']});
      if(group)group.documents.push(index);
    };
    for(let i=0;i<20;i++)add('baseline-'+i,'2026-10-10','papers');
    for(let i=0;i<groupCount;i++){
      const group={id:'group-'+i,kind:'group',label:i===0?'procedural memory':'topic '+i,
        family:family||(i===0?'research':'development'),
        terms:i===0?['procedural memory','persistent assistants']:['topic '+i],
        documents:[],article_count:0,links:[]};
      if(i===0)for(let j=0;j<previousSize;j++)add('old-group-'+j,'2026-10-10','papers',group);
      for(let j=0;j<(i===0?firstSize:2);j++)add('g'+i+'-'+j,j%2?'2026-10-19':'2026-10-18',i===0?'papers':'community',group);
      group.article_count=group.documents.length;groups.push(group);
    }
    const reports=Array.from({length:14},(_,i)=>({date:new Date(Date.UTC(2026,9,6+i)).toISOString().slice(0,10),
      coverage:{github:'ok',papers:'ok',community:'ok',cncf:'ok'}}));
    const bucket=(from,to)=>{
      const indices=items.flatMap((item,i)=>item.date>=from&&item.date<=to?[i]:[]);
      const available=reports.filter(r=>r.date>=from&&r.date<=to);
      return {from,to,item_count:indices.length,report_count:available.length,
        expected_days:(Date.parse(to)-Date.parse(from))/86400000+1,partial_slots:0,
        node_counts:Object.fromEntries(groups.map(g=>[g.id,g.documents.filter(i=>indices.includes(i)).length]))};
    };
    const data={meta:{from:'2026-10-06',to:'2026-10-19'},reports,tags:[{id:'memory',label:'메모리'}],
      items,details,nodes:[],links:[],
      article_groups:{groups,periods:{week:[bucket('2026-10-05','2026-10-11'),bucket('2026-10-12','2026-10-18'),bucket('2026-10-19','2026-10-19')],
        month:[bucket('2026-10-01','2026-10-19')]}}};
    document.getElementById('snapshot').textContent=JSON.stringify(data);
  },{groupCount,firstSize,previousSize,family});
  for(const file of ['analytics.js','ui.js'])await page.addScriptTag({content:fs.readFileSync(path.join(__dirname,file),'utf8')});
  return page;
}
test('today-relative discovery exposes only three simple period choices',async t=>{
  const page=await populated(t);
  assert.equal(await page.locator('#span').inputValue(),'7');
  assert.deepEqual(await page.locator('#span option').evaluateAll(es=>es.map(e=>e.value)),['3','7','30']);
  assert.equal(await page.locator('#as-of,#kind,[data-layout],#node-search').count(),0);
  assert.equal(await page.locator('#period-label').innerText(),'2026-10-13 — 2026-10-19');
  assert.equal(await page.locator('#data-through').innerText(),'최신 수록 2026-10-19');
});
test('group selection reveals original source titles and common expressions',async t=>{
  const page=await populated(t);
  assert.equal(await page.locator('#detail-title').innerText(),'procedural memory');
  assert.equal(await page.locator('#evidence-count').innerText(),'4건');
  assert.ok((await page.locator('#group-terms').innerText()).includes('procedural memory'));
  await page.locator('#group-list [data-group="group-1"]').click();
  assert.equal(await page.locator('#detail-title').innerText(),'topic 1');
  assert.equal(await page.locator('#evidence-count').innerText(),'2건');
  assert.ok(await page.locator('.evidence').evaluateAll(es=>es.every(e=>e.dataset.id.startsWith('g1-'))));
});
test('connected historical articles are explicit and do not change the current window',async t=>{
  const page=await populated(t);
  const range=await page.locator('#period-label').innerText();
  await page.locator('#group-history').click();
  assert.equal(await page.locator('#evidence-count').innerText(),'5건');
  assert.equal(await page.locator('#evidence-period').innerText(),'누적 관련 글');
  assert.equal(await page.locator('#period-label').innerText(),range);
  await page.locator('#group-history').click();
  assert.equal(await page.locator('#evidence-count').innerText(),'4건');
});
test('section and tag filters preserve today-relative windows',async t=>{
  const page=await populated(t);
  await page.locator('#span').selectOption('3');
  await page.locator('#section-tabs [data-section="papers"]').click();
  await page.locator('#tag').selectOption('memory');
  assert.equal(await page.locator('#period-label').innerText(),'2026-10-17 — 2026-10-19');
  assert.ok(await page.locator('.evidence-meta').evaluateAll(es=>es.every(e=>e.textContent.includes('AI 논문'))));
  await page.locator('#reset').click();
  assert.equal(await page.locator('#span').inputValue(),'7');
});
test('stale archives do not shift the window backwards or invent observations',async t=>{
  const page=await populated(t);
  await page.clock.setFixedTime(new Date('2026-10-30T03:00:00Z'));
  await page.evaluate(()=>window.dispatchEvent(new Event('focus')));
  assert.equal(await page.locator('#period-label').innerText(),'2026-10-24 — 2026-10-30');
  assert.equal(await page.locator('#data-through').innerText(),'최신 수록 2026-10-19 · 이후 미수록');
  assert.equal(await page.locator('#evidence-count').innerText(),'0건');
  assert.equal(await page.locator('#comparison-label').innerText(),'비교 자료 부족');
});
test('a trailing collection gap is explicit even when recent groups remain visible',async t=>{
  const page=await populated(t);
  await page.clock.setFixedTime(new Date('2026-10-21T03:00:00Z'));
  await page.evaluate(()=>window.dispatchEvent(new Event('focus')));
  assert.equal(await page.locator('#period-label').innerText(),'2026-10-15 — 2026-10-21');
  assert.equal(await page.locator('#data-through').innerText(),'최신 수록 2026-10-19 · 이후 미수록');
  assert.ok(await page.locator('#heatmap [data-group]').count()>0);
});
test('group search preserves count ordering within a family',async t=>{
  const page=await populated(t,{firstSize:5,previousSize:20,family:'research'});
  await page.locator('#ordering').selectOption('count');
  const ids=()=>page.locator('#group-list [data-group]').evaluateAll(es=>es.map(e=>e.dataset.group));
  assert.deepEqual(await ids(),['group-0','group-1']);
  await page.locator('#group-search').fill('t');
  assert.deepEqual(await ids(),['group-0','group-1']);
});
test('rising-mode search can still find a non-rising related group',async t=>{
  const page=await populated(t,{firstSize:2,previousSize:20});
  assert.equal(await page.locator('#group-list [data-group="group-0"]').count(),0);
  await page.locator('#group-search').fill('procedural memory');
  assert.equal(await page.locator('#group-list [data-group="group-0"]').count(),1);
  await page.locator('#group-list [data-group="group-0"]').click();
  assert.deepEqual(await page.locator('#heatmap .group-family th').allTextContents(),['논문 관련','개발·커뮤니티']);
});
test('inventory, text search and keyboard pagination preserve source access',async t=>{
  const page=await populated(t,{groupCount:30,firstSize:26});
  await page.locator('#inventory').click();
  assert.equal(await page.locator('#evidence-count').innerText(),'84건');
  await page.locator('#evidence-search').fill('g0-0');
  assert.equal(await page.locator('#evidence-count').innerText(),'1건');
  await page.locator('#evidence-search').fill('no-such-term');
  assert.equal(await page.locator('#evidence-count').innerText(),'0건');
  await page.locator('#reset').click();
  await page.locator('#more-evidence').focus();
  await page.locator('#more-evidence').press('Enter');
  await page.locator('#more-evidence').press('Space');
  assert.equal(await page.locator('.evidence').count(),26);
  assert.ok(await page.locator('#more-evidence').isHidden());
  assert.equal(await page.evaluate(()=>document.activeElement.id),'detail-panel');
  await page.locator('#more-groups').focus();await page.locator('#more-groups').press('Enter');
  assert.ok(await page.locator('#more-groups').isHidden());
  assert.equal(await page.evaluate(()=>document.activeElement.id),'group-search');
});
test('heatmap selection changes the reading group, not the calendar anchor',async t=>{
  const page=await populated(t);
  const period=await page.locator('#period-label').innerText();
  await page.locator('#heatmap [data-group="group-1"]').first().click();
  assert.equal(await page.locator('#detail-title').innerText(),'topic 1');
  assert.equal(await page.locator('#period-label').innerText(),period);
});
test('archive and grouped page share branding with plain active navigation',async t=>{
  const atlas=await populated(t),archive=await browser.newPage();t.after(()=>archive.close());
  await archive.route(/^https?:/,route=>route.abort());await archive.emulateMedia({reducedMotion:'reduce'});
  const template=fs.readFileSync(path.join(siteRoot,'template.html'),'utf8')
    .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi,'')
    .replace('@@SITE_STYLE@@',fs.readFileSync(path.join(siteRoot,'site-theme.css'),'utf8'))
    .replace('@@SITE_HEADER@@',header('./','archive')).replaceAll('@@BASE@@','./').replace('@@CONTENT@@','<h1>Archive fixture</h1>');
  await archive.setContent(template);
  const branding=page=>page.evaluate(()=>({
    font:getComputedStyle(document.body).fontFamily,background:getComputedStyle(document.body).backgroundColor,
    header:getComputedStyle(document.querySelector('.site-header')).backgroundColor,
    logo:document.querySelector('.site-brand-mark').outerHTML,
    accent:getComputedStyle(document.body).getPropertyValue('--cp-accent')
  }));
  for(const width of [390,768,1360])for(const theme of ['light','dark']){
    for(const page of [atlas,archive]){
      await page.setViewportSize({width,height:1000});await page.evaluate(theme=>document.documentElement.dataset.theme=theme,theme);
      assert.ok(await page.locator('.header-links [data-site-link="insights"]').isVisible());
      assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    }
    assert.deepEqual(await branding(atlas),await branding(archive));
    assert.equal(await atlas.locator('[data-site-link="insights"]').getAttribute('aria-current'),'page');
    const state=await atlas.locator('[data-site-link="insights"]').evaluate(e=>{
      const s=getComputedStyle(e);return {background:s.backgroundColor,border:s.borderTopWidth,line:s.textDecorationLine};
    });
    assert.equal(state.background,'rgba(0, 0, 0, 0)');assert.equal(state.border,'0px');assert.ok(state.line.includes('underline'));
  }
});
test('explicit site theme overrides the system preference',async t=>{
  const page=await shell(t);await page.emulateMedia({colorScheme:'dark'});
  await page.route('https://theme.test/**',route=>route.fulfill({body:'<html><body></body></html>',contentType:'text/html'}));
  const script=fs.readFileSync(path.join(siteRoot,'site-theme.js'),'utf8');
  await page.goto('https://theme.test/?scoutTheme=light');await page.addScriptTag({content:script});
  assert.equal(await page.locator('html').getAttribute('data-theme'),'light');
  await page.goto('https://theme.test/?scoutTheme=invalid');await page.addScriptTag({content:script});
  assert.equal(await page.locator('html').getAttribute('data-theme'),'dark');
});
function domIds(source){
  const ids=[];
  function visit(node){
    if(!node||typeof node!=='object')return;
    if(node.type==='CallExpression'&&node.callee.type==='Identifier'&&node.callee.name==='$'){
      const a=node.arguments[0];
      if(a?.type==='Literal'&&typeof a.value==='string')ids.push(a.value);
      if(a?.type==='TemplateLiteral'&&!a.expressions.length)ids.push(a.quasis[0].value.cooked);
    }
    for(const value of Object.values(node))if(Array.isArray(value))value.forEach(visit);else if(value&&typeof value==='object')visit(value);
  }
  visit(parse(source,{ecmaVersion:'latest'}));return ids;
}
test('literal grouped UI DOM references exist in the actual template',async t=>{
  const page=await shell(t),ids=new Set(await page.locator('[id]').evaluateAll(es=>es.map(e=>e.id)));
  for(const id of domIds(fs.readFileSync(path.join(__dirname,'ui.js'),'utf8')))assert.ok(ids.has(id),'Missing target: '+id);
});
test('DOM parser handles spacing, comments and escaped literals without matching ordinary strings',()=>{
  assert.deepEqual(domIds("$ /* x */ ('missing\\u002dtarget'); $(`other`); const s=\"$('not-a-call')\";"),['missing-target','other']);
});
async function neutral(page){
  const texts=await page.evaluate(()=>[document.body.innerText,...[...document.querySelectorAll('[aria-label],[title],[placeholder]')].flatMap(e=>['aria-label','title','placeholder'].map(k=>e.getAttribute(k)||''))]);
  for(const text of texts)for(const forbidden of ['MODEL CALLS','STATIC GRAPH','다음 질문','해보세요','준비할지']){
    assert.ok(!text.normalize('NFKC').replace(/\s+/gu,' ').includes(forbidden),'Disallowed interface copy: '+forbidden);
  }
}
test('grouped interface does not add generated reading advice',async t=>{await neutral(await populated(t));});
test('rendered copy guard detects runtime concatenation in text and labels',async t=>{
  const page=await populated(t);
  for(const attribute of ['text','aria-label','title','placeholder']){
    await page.evaluate(attribute=>{
      const e=document.createElement('input');e.id='bad-copy';const text='다음 '+'질문';
      if(attribute==='text'){const p=document.createElement('p');p.id='bad-copy';p.textContent=text;document.body.append(p);}
      else{e.setAttribute(attribute,text);document.body.append(e);}
    },attribute);
    await assert.rejects(neutral(page),/Disallowed interface copy/);
    await page.locator('#bad-copy').evaluate(e=>e.remove());
  }
});
test('group count labels and missing-data cells are readable in both themes',async t=>{
  const page=await populated(t);
  const luminance=rgb=>{
    const values=rgb.match(/[\d.]+/g).slice(0,3).map(Number).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4;});
    return values[0]*.2126+values[1]*.7152+values[2]*.0722;
  };
  for(const theme of ['light','dark']){
    await page.evaluate(theme=>document.documentElement.dataset.theme=theme,theme);
    await page.locator('#reset').click();
    const styles=await page.locator('#heatmap td button').evaluateAll(es=>es.map(e=>{
      const s=getComputedStyle(e);return {fg:s.color,bg:s.backgroundColor};
    }));
    assert.ok(styles.length);
    for(const {fg,bg} of styles){const a=luminance(fg),b=luminance(bg);assert.ok((Math.max(a,b)+.05)/(Math.min(a,b)+.05)>=4.5);}
  }
});
