(function () {
  'use strict';
  const $ = id => document.getElementById(id);
  const D = JSON.parse($('snapshot').textContent), A = globalThis.BriefAtlas;
  const nodes = new Map(D.nodes.map(n => [n.id, n]));
  const compactGraph = matchMedia('(max-width:500px)');
  const KINDS = { phrase: '표현', project: '프로젝트', name: '이름·약어' };
  const SECTIONS = { github: 'GitHub', papers: 'AI 논문', community: '커뮤니티', cncf: 'CNCF' };
  const renderer = new globalThis.AtlasGraphRenderer($('graph'));
  const esc = value => String(value).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const clip = (text, max) => text.length > max ? text.slice(0, max) + '…' : text;
  const short = day => day ? day.slice(5).replace('-', '.') : '—';
  const initial = new URLSearchParams(location.hash.slice(1)).get('node');
  const state = { asOf: D.meta.to, span: 'all', kind: nodes.get(initial)?.kind || 'phrase', section: '', tag: '',
    custom: null, unit: 'week', focus: nodes.has(initial) ? initial : '', pair: '', inventory: false,
    minimum: 1, cross: false, nodeQuery: '', limitNodes: 24, q: '', limit: 5, layout: 'network', explicitFocus: false };
  let view;
  function clearSelection() { state.pair = ''; state.q = ''; state.limit = 5; $('evidence-search').value = ''; }
  function sectionCards() {
    const total = Object.values(view.sectionTotals).reduce((sum, n) => sum + n, 0);
    $('section-cards').innerHTML = [['', '전체'], ...Object.entries(SECTIONS)].map(([id, label]) => `<button type="button" data-section="${id}" class="${state.section === id ? 'active' : ''}" aria-pressed="${state.section === id}">${label}<span>${id ? view.sectionTotals[id] : total}</span></button>`).join('');
  }
  function graph() {
    const model = globalThis.GraphViews.project(D, view, state.focus, {
      limit: compactGraph.matches ? 14 : 24, minimum: state.minimum, cross: state.cross,
      pair: state.pair, keepFocus: state.explicitFocus
    });
    const shown = renderer.render(model, { mode: state.layout, focus: state.focus, pair: state.pair, compact: compactGraph.matches });
    $('view-count').textContent = `${shown} / ${model.total}`;
    document.querySelectorAll('[data-layout]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.layout === state.layout)));
    for (const id of ['zoom-in', 'zoom-out', 'fit-view']) $(id).disabled = state.layout === 'matrix';
  }
  function heatmap() {
    const visible = view.rows.slice(0, 6);
    const selected = view.allRows.find(n => n.id === state.focus && n.kind === state.kind);
    if (selected && !visible.some(n => n.id === selected.id)) visible.push(selected);
    const rows = visible.map(n => ({ node: n, periods: A.series(D, view, n.id, state.unit) }));
    const buckets = rows[0]?.periods || [];
    const max = Math.max(1, ...rows.flatMap(r => r.periods.map(b => b.count)));
    $('heatmap').innerHTML = `<thead><tr><th></th>${buckets.map(b => `<th scope="col" title="${b.from} — ${b.to}${b.report_count < (b.expected_days || 1) || b.partial_slots ? ' · 부분 수집' : ''}">${short(b.from)}${b.report_count < (b.expected_days || 1) || b.partial_slots ? ' *' : ''}</th>`).join('')}</tr></thead>
      <tbody>${rows.map(({ node, periods }) => `<tr><th scope="row"><button type="button" data-node="${node.id}" title="${esc(node.label)}" class="${node.id === state.focus ? 'selected-label' : ''}">${esc(clip(node.label, 31))}</button></th>${periods.map(b => {
        const strength = b.count / max;
        const shades = ['#f3f5f7', '#e4ebf4', '#c3d0e2', '#8299b8', '#45648d'];
        const level = Math.ceil(strength * 4);
        const color = `background:${shades[level]};color:${level === 4 ? '#fff' : '#000'}`;
        return `<td><button type="button" data-cell="${node.id}" data-from="${b.from}" data-to="${b.to}" class="${b.available ? '' : 'no-data'}" style="${b.available ? color : ''}" aria-label="${esc(node.label)} ${b.from}부터 ${b.to}, ${b.available ? b.count + '건' : '관측 없음'}">${b.available ? b.count : '—'}</button></td>`;
      }).join('')}</tr>`).join('')}</tbody>`;
    if (!rows.length) $('heatmap').innerHTML = '<tbody><tr><td>기록 없음</td></tr></tbody>';
  }
  function nodeList() {
    const q = state.nodeQuery.normalize('NFKC').toLowerCase().trim();
    const matches = view.rows.filter(n => n.label.normalize('NFKC').toLowerCase().includes(q));
    $('node-count').textContent = `${matches.length}개`;
    $('node-list').innerHTML = matches.slice(0, state.limitNodes).map(n => `<button type="button" class="topic-chip${n.id === state.focus ? ' selected' : ''}" data-node="${n.id}">${esc(n.label)} <span>${n.count}</span></button>`).join('') || '<p class="empty">결과 없음</p>';
    $('more-nodes').hidden = matches.length <= state.limitNodes;
  }
  function selectedEvidence() {
    return A.evidence(D, view, state.inventory ? [] : [state.focus, state.pair].filter(Boolean));
  }
  function detail() {
    const node = view.allRows.find(n => n.id === state.focus);
    const other = state.pair ? nodes.get(state.pair) : null;
    $('detail-kind').textContent = state.inventory || !node ? '소식' : KINDS[node.kind];
    $('detail-title').textContent = state.inventory || !node ? '전체 소식' : node.label + (other ? ' × ' + other.label : '');
    $('clear-pair').hidden = !state.pair;
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
    $('evidence-list').innerHTML = matches.slice(0, state.limit).map(item => {
      const detail = D.details[item.index];
      return `<article class="evidence" data-id="${esc(item.id)}"><div class="evidence-meta">${item.date} · ${SECTIONS[item.section]}</div>
        <h3><a href="${esc(item.href)}" target="_blank" rel="noopener noreferrer">${esc(item.title)}</a></h3>
        <div class="evidence-actions"><a href="${esc(item.url)}" target="_blank" rel="noopener noreferrer">원문 ↗</a>
        ${detail.summary ? `<details class="excerpt"><summary>요약</summary><p>${esc(detail.summary)}</p></details>` : ''}</div></article>`;
    }).join('') || '<p class="empty">소식 없음</p>';
    $('more-evidence').hidden = matches.length <= state.limit;
  }
  function render() {
    view = A.query(D, state);
    if (!state.inventory) {
      const focus = A.selectFocus(D, view, state.focus, { explicit: state.explicitFocus });
      if (focus !== state.focus) state.pair = '';
      state.focus = focus;
    }
    $('kind').value = state.kind; $('span').value = state.custom ? 'custom' : state.span;
    $('period-label').textContent = `${view.range.from} — ${view.range.to}`;
    $('sample-label').textContent = `${view.total}건`;
    $('sample-label').title = `중복 제외 · 게재 기록 ${view.occurrences}건`;
    document.querySelectorAll('[data-unit]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.unit === state.unit)));
    sectionCards(); graph(); heatmap(); nodeList(); detail();
  }
  function choose(id) {
    const node = nodes.get(id);
    if (!node) throw new Error('Unknown graph node: ' + id);
    state.focus = id; state.kind = node.kind; state.inventory = false; state.explicitFocus = true; clearSelection(); render();
  }
  function act(event) {
    const button = event.target.closest('[data-node],[data-edge-source],[data-layout],[data-cell],[data-unit],[data-section]');
    if (!button) return;
    if (button.dataset.node) choose(button.dataset.node);
    else if (button.dataset.edgeSource) {
      state.focus = button.dataset.edgeSource; state.pair = button.dataset.edgeTarget;
      state.kind = nodes.get(state.focus).kind; state.explicitFocus = true;
      state.inventory = false; state.q = ''; $('evidence-search').value = ''; render();
    }
    else if (button.dataset.layout) { state.layout = button.dataset.layout; graph(); }
    else if (button.dataset.cell) {
      state.focus = button.dataset.cell; state.inventory = false; state.explicitFocus = true; state.custom = { from: button.dataset.from, to: button.dataset.to };
      clearSelection(); render();
    } else if (button.dataset.unit) { state.unit = button.dataset.unit; heatmap(); document.querySelectorAll('[data-unit]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.unit === state.unit))); }
    else { state.section = state.section === button.dataset.section ? '' : button.dataset.section; state.explicitFocus = false; clearSelection(); render(); }
    if ((event.type === 'keydown' || event.detail === 0) && !button.isConnected) $('detail-panel').focus({ preventScroll: true });
    if ((button.dataset.node || button.dataset.edgeSource) && matchMedia('(max-width:800px)').matches) $('detail-panel').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
  globalThis.addEventListener('error', e => { $('fatal').hidden = false; $('fatal').textContent = '그래프 조회 오류: ' + e.message + ' · 페이지를 다시 열어 주세요.'; });
  $('as-of').innerHTML = [...D.reports].reverse().map(r => `<option value="${r.date}">${r.date}</option>`).join('');
  $('tag').innerHTML += D.tags.map(t => `<option value="${esc(t.id)}">${esc(t.label)}</option>`).join('');
  document.addEventListener('click', act);
  document.addEventListener('keydown', e => { if (e.target.matches('g[role=button]') && ['Enter', ' '].includes(e.key)) { e.preventDefault(); act(e); } });
  for (const [id, key] of [['kind', 'kind'], ['span', 'span'], ['as-of', 'asOf'], ['tag', 'tag']]) {
    $(id).addEventListener('change', e => { state[key] = e.target.value; state.custom = null; state.inventory = false; state.explicitFocus = false; clearSelection(); render(); });
  }
  $('minimum').addEventListener('change', e => { state.minimum = Number(e.target.value); clearSelection(); graph(); detail(); });
  $('cross-kind').addEventListener('change', e => { state.cross = e.target.checked; clearSelection(); graph(); detail(); });
  $('evidence-search').addEventListener('input', e => { state.q = e.target.value; state.limit = 5; renderEvidence(); });
  $('node-search').addEventListener('input', e => { state.nodeQuery = e.target.value; state.limitNodes = 24; nodeList(); });
  $('more-evidence').addEventListener('click', () => { state.limit += 10; renderEvidence(); });
  $('more-nodes').addEventListener('click', () => { state.limitNodes += 24; nodeList(); });
  $('clear-pair').addEventListener('click', () => { clearSelection(); graph(); detail(); });
  $('inventory').addEventListener('click', () => { state.inventory = true; state.focus = ''; state.explicitFocus = false; clearSelection(); render(); });
  $('reset').addEventListener('click', () => {
    Object.assign(state, { asOf: D.meta.to, span: 'all', kind: 'phrase', section: '', tag: '', custom: null, focus: '', pair: '', inventory: false, nodeQuery: '', limitNodes: 24, minimum: 1, cross: false, unit: 'week', layout: 'network', explicitFocus: false });
    $('as-of').value = state.asOf; $('tag').value = ''; $('node-search').value = ''; $('minimum').value = '1'; $('cross-kind').checked = false; clearSelection(); render();
  });
  $('zoom-in').addEventListener('click', () => renderer.zoomBy(1.3));
  $('zoom-out').addEventListener('click', () => renderer.zoomBy(1 / 1.3));
  $('fit-view').addEventListener('click', () => renderer.reset());
  compactGraph.addEventListener('change', graph);
  render();
})();
