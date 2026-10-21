(function () {
  'use strict';
  const $ = id => document.getElementById(id);
  const A = globalThis.BriefAtlas;
  const D = A.forGroups(JSON.parse($('snapshot').textContent));
  const groups = new Map(D.nodes.map(group => [group.id, group]));
  const SECTIONS = {github: 'GitHub', papers: 'AI 논문', community: '커뮤니티', cncf: 'CNCF'};
  const FAMILIES = {research: '논문 관련', development: '개발·커뮤니티', platform: '클라우드 네이티브'};
  const familyOrder = Object.keys(FAMILIES);
  const esc = text => String(text).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const short = day => day.slice(5).replace('-', '.');
  const initial = new URLSearchParams(location.hash.slice(1)).get('group');
  const state = {
    asOf: A.kstDay(), span: '7', kind: 'group', section: '', tag: '', unit: 'week',
    focus: groups.has(initial) ? initial : '', explicit: groups.has(initial),
    inventory: false, history: false, ordering: 'rising', search: '', q: '', limit: 6, limitGroups: 24
  };
  let view, trend;

  function orderGroups(rows) {
    return [...rows].sort((a,b)=>
      familyOrder.indexOf(a.family)-familyOrder.indexOf(b.family) ||
      (state.ordering === 'rising' && trend.comparable ? b.delta-a.delta : b.count-a.count) ||
      b.count-a.count || a.label.localeCompare(b.label));
  }
  function clearEvidence() {
    state.history = false; state.q = ''; state.limit = 6;
    $('evidence-search').value = '';
  }
  function recoverFocus(event, control, target = 'detail-panel') {
    if ((event.type === 'keydown' || event.detail === 0) && (!control.isConnected || control.hidden)) {
      $(target).focus({preventScroll: true});
    }
  }
  function sectionTabs() {
    const total = Object.values(view.sectionTotals).reduce((sum, value) => sum + value, 0);
    $('section-tabs').innerHTML = [['', '전체'], ...Object.entries(SECTIONS)].map(([id, label]) =>
      `<button type="button" data-section="${id}" class="${state.section === id ? 'active' : ''}" aria-pressed="${state.section === id}">${label}<span>${id ? view.sectionTotals[id] : total}</span></button>`
    ).join('');
  }
  function heatmap() {
    let rows = familyOrder.flatMap(family => view.rows.filter(group => group.family === family).slice(0, 5));
    const selected = trend.allRows.find(group => group.id === state.focus);
    if (selected && !rows.some(group => group.id === selected.id)) rows.push(selected);
    rows = orderGroups(rows);
    const series = new Map(rows.map(group => [group.id, A.series(D, view, group.id, state.unit).slice(-6)]));
    const periods = series.get(rows[0]?.id) || [];
    const maximum = Math.max(1, ...[...series.values()].flatMap(values => values.map(value => value.count)));
    const dark = document.documentElement.dataset.theme === 'dark';
    const shades = dark ? ['#343231','#5a3a43','#86505f','#c4778b','#fd8ea1']
      : ['#f5f2ef','#f4e4e9','#e8becb','#ad4666','#92203f'];
    $('comparison-label').textContent = trend.comparable
      ? `${short(trend.previous.range.from)}–${short(trend.previous.range.to)} → ${short(view.range.from)}–${short(view.range.to)}`
      : '비교 자료 부족';
    let lastFamily = '';
    $('heatmap').innerHTML = `<thead><tr><th></th><th scope="col">이전</th><th scope="col">최근</th><th scope="col" title="전체 고유 글 대비 비중 차이">%p</th>${periods.map(period =>
      `<th scope="col" title="${period.from} — ${period.to}">${short(period.from)}${period.partial_slots || period.report_count < period.expected_days ? '*' : ''}</th>`
    ).join('')}</tr></thead><tbody>${rows.map(group => {
      const family = group.family;
      const separator = family !== lastFamily ? `<tr class="group-family"><th colspan="${periods.length + 4}" scope="rowgroup">${FAMILIES[family]}</th></tr>` : '';
      lastFamily = family;
      return `${separator}<tr><th scope="row"><button type="button" data-group="${group.id}" class="${group.id === state.focus ? 'selected-label' : ''}">${esc(group.label)}</button><small>${group.sections.map(section => SECTIONS[section]).join(' · ')}</small></th>
      <td class="change-count">${group.previousCount}</td><td class="change-count">${group.count}</td>
      <td class="change-delta" title="${group.previousCount}/${trend.previous.total} → ${group.count}/${view.total}">${group.delta === null ? '—' : (group.delta > 0 ? '+' : '') + group.delta.toFixed(1)}</td>
      ${series.get(group.id).map(period => {
        const level = Math.ceil(4 * period.count / maximum);
        const color = dark ? (level >= 3 ? '#161616' : '#fff') : (level >= 3 ? '#fff' : '#242424');
        return `<td><button type="button" data-group="${group.id}" class="${period.available ? '' : 'no-data'}" style="${period.available ? `background:${shades[level]};color:${color}` : ''}" title="${period.from} — ${period.to}" aria-label="${esc(group.label)}, ${period.from}부터 ${period.to}, ${period.available ? period.count + '건' : '관측 없음'}">${period.available ? period.count : '—'}</button></td>`;
      }).join('')}</tr>`;
    }).join('')}</tbody>`;
    if (!rows.length) $('heatmap').innerHTML = `<tbody><tr><td>${view.total ? '조건에 맞는 글 묶음 없음' : '최근 수록된 글 없음'}</td></tr></tbody>`;
  }
  function groupList() {
    const query = state.search.normalize('NFKC').toLowerCase().trim();
    const candidates = query && state.ordering === 'rising' ? orderGroups(trend.rows) : view.rows;
    const matches = candidates.filter(group => [group.label, ...group.terms].join(' ').normalize('NFKC').toLowerCase().includes(query));
    $('group-count').textContent = `${matches.length}개`;
    $('group-list').innerHTML = matches.slice(0, state.limitGroups).map(group =>
      `<button type="button" data-group="${group.id}" class="topic-chip${group.id === state.focus ? ' selected' : ''}">${esc(group.label)}<span>${group.count}</span></button>`
    ).join('') || '<p class="empty">묶음 없음</p>';
    $('more-groups').hidden = matches.length <= state.limitGroups;
  }
  function evidenceView() {
    return state.history && !state.inventory ? A.query(D, {...state, span:'all'}) : view;
  }
  function selectedEvidence() {
    if (!state.focus && !state.inventory) return [];
    return A.evidence(D, evidenceView(), state.inventory ? [] : [state.focus]);
  }
  function detail() {
    const group = groups.get(state.focus);
    $('detail-title').textContent = state.inventory ? '전체 소식' : group?.label || '선택된 묶음 없음';
    $('group-terms').innerHTML = state.inventory || !group ? '' : group.terms.map(term => `<span>${esc(term)}</span>`).join('');
    $('evidence-period').textContent = state.history ? '누적 관련 글' : `최근 ${state.span}일`;
    const allCount = group ? A.evidence(D, A.query(D, {...state, span:'all'}), [group.id]).length : 0;
    const currentCount = group ? A.evidence(D, view, [group.id]).length : 0;
    $('group-history').hidden = state.inventory || !group || allCount <= currentCount;
    $('group-history').textContent = state.history ? `최근 ${state.span}일만` : `연결 글 전체 ${allCount}건`;
    renderEvidence();
  }
  function renderEvidence() {
    const terms = state.q.normalize('NFKC').toLowerCase().split(/\s+/u).filter(Boolean);
    const matches = selectedEvidence().filter(item => {
      const detail = D.details[item.index];
      const text = [item.title, detail.body, ...(detail.topics || [])].join(' ').normalize('NFKC').toLowerCase();
      return terms.every(term => text.includes(term));
    });
    $('evidence-count').textContent = `${matches.length}건`;
    $('evidence-list').innerHTML = matches.slice(0,state.limit).map(item => {
      const detail = D.details[item.index];
      return `<article class="evidence" data-id="${esc(item.id)}"><div class="evidence-meta">${item.date} · ${SECTIONS[item.section]}</div>
        <h3><a href="${esc(item.href)}" target="_blank" rel="noopener noreferrer">${esc(item.title)}</a></h3>
        <div class="evidence-actions"><a href="${esc(item.url)}" target="_blank" rel="noopener noreferrer">원문 ↗</a>
        ${detail.summary ? `<details class="excerpt"><summary>요약</summary><p>${esc(detail.summary)}</p></details>` : ''}</div></article>`;
    }).join('') || '<p class="empty">소식 없음</p>';
    $('more-evidence').hidden = matches.length <= state.limit;
  }
  function render() {
    trend = A.recent(D,state);
    const rows = orderGroups(state.ordering === 'rising' && trend.comparable ? trend.rising : trend.rows);
    view = {...trend.current,rows};
    if (!state.inventory && (!state.explicit || !groups.has(state.focus))) state.focus = rows[0]?.id || '';
    $('span').value = state.span; $('ordering').value = state.ordering;
    $('period-label').textContent = `${view.range.from} — ${view.range.to}`;
    $('data-through').textContent = `최신 수록 ${D.meta.to}${D.meta.to < state.asOf ? ' · 이후 미수록' : ''}`;
    $('sample-label').textContent = `${view.total}개 글`;
    document.querySelectorAll('[data-unit]').forEach(button => button.setAttribute('aria-pressed',String(button.dataset.unit === state.unit)));
    sectionTabs();heatmap();groupList();detail();
  }
  function refreshToday() {
    const today = A.kstDay();
    if (today !== state.asOf) {
      state.asOf = today;state.explicit = false;clearEvidence();render();
    }
  }
  document.addEventListener('click', event => {
    const button = event.target.closest('[data-group],[data-unit],[data-section]');
    if (!button) return;
    if (button.dataset.group) {
      if (!groups.has(button.dataset.group)) throw new Error('Unknown article group');
      state.focus = button.dataset.group;state.explicit = true;state.inventory = false;clearEvidence();render();
    } else if (button.dataset.unit) {
      state.unit = button.dataset.unit;render();
    } else {
      state.section = button.dataset.section;state.explicit = false;state.inventory = false;clearEvidence();render();
    }
    recoverFocus(event,button);
  });
  for (const [id,key] of [['span','span'],['tag','tag'],['ordering','ordering']]) {
    $(id).addEventListener('change',event=>{state[key]=event.target.value;state.asOf=A.kstDay();state.explicit=false;state.inventory=false;clearEvidence();render();});
  }
  $('group-search').addEventListener('input',event=>{state.search=event.target.value;state.limitGroups=24;groupList();});
  $('evidence-search').addEventListener('input',event=>{state.q=event.target.value;state.limit=6;renderEvidence();});
  $('more-groups').addEventListener('click',event=>{state.limitGroups+=24;groupList();recoverFocus(event,event.currentTarget,'group-search');});
  $('more-evidence').addEventListener('click',event=>{state.limit+=10;renderEvidence();recoverFocus(event,event.currentTarget);});
  $('group-history').addEventListener('click',()=>{state.history=!state.history;state.limit=6;detail();});
  $('inventory').addEventListener('click',()=>{state.inventory=true;state.focus='';state.explicit=false;clearEvidence();render();});
  $('reset').addEventListener('click',()=>{
    Object.assign(state,{asOf:A.kstDay(),span:'7',section:'',tag:'',unit:'week',ordering:'rising',focus:'',explicit:false,inventory:false,search:'',limitGroups:24});
    $('tag').value='';$('group-search').value='';clearEvidence();render();
  });
  globalThis.addEventListener('focus',refreshToday);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)refreshToday();});
  globalThis.addEventListener('error',event=>{$('fatal').hidden=false;$('fatal').textContent='탐색 오류: '+event.message;});
  $('tag').innerHTML += D.tags.map(tag=>`<option value="${esc(tag.id)}">${esc(tag.label)}</option>`).join('');
  render();
})();
