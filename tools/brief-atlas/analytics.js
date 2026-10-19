(function (root) {
  'use strict';
  const sections = ['github', 'papers', 'community', 'cncf'];
  const kinds = ['phrase', 'project', 'name'];
  function date(value) {
    const result = new Date(value + 'T00:00:00Z');
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value) || !Number.isFinite(+result) || result.toISOString().slice(0, 10) !== value) throw new Error('Invalid date: ' + value);
    return result;
  }
  const shift = (value, days) => new Date(+date(value) + days * 86400000).toISOString().slice(0, 10);
  const unique = (data, indices) => new Set(indices.map(i => data.items[i].identity)).size;
  function stats(data, node, indices, history) {
    const documents = node.documents.filter(i => indices.has(i));
    const observed = node.documents.filter(i => history.has(i));
    const dates = observed.map(i => data.items[i].date).sort();
    return { ...node, documents, count: unique(data, documents), occurrences: documents.length,
      first: dates[0] || null, last: dates.at(-1) || null,
      days: new Set(documents.map(i => data.items[i].date)).size,
      sections: [...new Set(documents.map(i => data.items[i].section))] };
  }
  function query(data, options) {
    const { asOf, span = 'all', kind = 'phrase', section = '', tag = '', custom = null } = options;
    date(asOf);
    if (!kinds.includes(kind)) throw new Error('Unknown node kind');
    if (section && !sections.includes(section)) throw new Error('Unknown section');
    if (tag && !data.tags.some(t => t.id === tag)) throw new Error('Unknown tag');
    if (!['all', '7', '30'].includes(span)) throw new Error('Unknown date span');
    const range = custom || { from: span === 'all' ? data.meta.from : shift(asOf, -Number(span) + 1), to: asOf };
    date(range.from); date(range.to);
    if (range.from > range.to || range.to > asOf) throw new Error('Invalid range');
    const match = item => (!section || item.section === section) && (!tag || item.tags.includes(tag));
    const indices = new Set(), history = new Set();
    const sectionTotals = Object.fromEntries(sections.map(s => [s, new Set()]));
    data.items.forEach((item, i) => {
      if (item.date <= asOf && match(item)) history.add(i);
      if (item.date < range.from || item.date > range.to || (tag && !item.tags.includes(tag))) return;
      sectionTotals[item.section].add(item.identity);
      if (match(item)) indices.add(i);
    });
    const allRows = data.nodes.map(node => stats(data, node, indices, history));
    const rows = allRows.filter(row => row.kind === kind && row.count > 0)
      .sort((a, b) => b.count - a.count || b.last.localeCompare(a.last) || a.label.localeCompare(b.label));
    return { options: { ...options, span, kind, section, tag }, range, indices, history, rows, allRows,
      total: unique(data, [...indices]), occurrences: indices.size,
      sectionTotals: Object.fromEntries(sections.map(s => [s, sectionTotals[s].size])) };
  }
  function evidence(data, view, nodeIds = []) {
    const latest = new Map();
    for (const i of view.indices) {
      const item = data.items[i];
      if (!nodeIds.every(id => item.nodes.includes(id))) continue;
      const previous = latest.get(item.identity);
      if (previous === undefined || data.items[previous].date < item.date) latest.set(item.identity, i);
    }
    return [...latest.values()].map(index => ({ ...data.items[index], index }))
      .sort((a, b) => b.date.localeCompare(a.date) || a.title.localeCompare(b.title));
  }
  function neighbors(data, view, focus, crossKinds, minimum) {
    const center = data.nodes.find(node => node.id === focus);
    if (!center) return [];
    const rows = new Map(view.allRows.map(n => [n.id, n]));
    return data.links.filter(edge => edge.source === focus || edge.target === focus).map(edge => {
      const other = edge.source === focus ? edge.target : edge.source;
      const documents = edge.documents.filter(i => view.indices.has(i));
      return { node: rows.get(other), count: unique(data, documents), documents };
    }).filter(edge => edge.count >= minimum && (crossKinds || edge.node.kind === center.kind))
      .sort((a, b) => b.count - a.count || a.node.label.localeCompare(b.node.label));
  }
  function series(data, view, focus, unit) {
    if (!['week', 'month'].includes(unit)) throw new Error('Unknown period unit');
    const { asOf, section, tag } = view.options;
    const precomputed = !section && !tag && asOf === data.meta.to;
    const node = data.nodes.find(n => n.id === focus);
    return data.periods[unit].filter(b => b.from <= asOf).map(b => {
      if (precomputed) return { ...b, count: b.node_counts[focus] || 0, available: b.report_count > 0 };
      const to = b.to < asOf ? b.to : asOf;
      const indices = [...view.history].filter(i => data.items[i].date >= b.from && data.items[i].date <= to);
      const nodeIndices = new Set(node?.documents || []);
      const reports = data.reports.filter(r => r.date >= b.from && r.date <= to);
      return { ...b, to, item_count: unique(data, indices), report_count: reports.length,
        count: unique(data, indices.filter(i => nodeIndices.has(i))), available: reports.length > 0 };
    });
  }
  const api = { query, evidence, neighbors, series };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.BriefAtlas = api;
})(globalThis);
