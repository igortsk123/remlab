// design-02 П2б2 (T-20261103-05): краткий обзор страницы (только чтение) — наборы, свойства, варианты (id, имя,
// размер), счётчики меток remlab/css по типу узла (FRAME/INSTANCE), число экземпляров внутри. Одна страница на вызов.
const PAGE_ID = '14:109';

const page = await figma.getNodeByIdAsync(PAGE_ID);
await figma.setCurrentPageAsync(page);
const sets = page.findAllWithCriteria({ types: ['COMPONENT_SET'] });
const out = { page: page.name, sets: [], loose: page.findAllWithCriteria({ types: ['COMPONENT'] }).filter(c => c.parent.type !== 'COMPONENT_SET').map(c => c.id + ' ' + c.name) };
for (const s of sets) {
  const defs = s.componentPropertyDefinitions;
  const row = { id: s.id, n: s.name, props: Object.entries(defs).map(([k, d]) => k + ':' + d.type[0] + (d.variantOptions ? '[' + d.variantOptions.join('|') + ']' : '')), v: [] };
  for (const v of s.children) {
    const css = {};
    v.findAll(n => { if (n.id.startsWith('I')) return false; const c = n.getSharedPluginData('remlab', 'css'); if (c) { const k = c + '/' + n.type[0]; css[k] = (css[k] || 0) + 1; } return false; });
    row.v.push({ id: v.id, n: v.name, wh: Math.round(v.width) + 'x' + Math.round(v.height), inst: v.findAllWithCriteria({ types: ['INSTANCE'] }).filter(n => !n.id.startsWith('I')).length, css });
  }
  out.sets.push(row);
}
return out;
