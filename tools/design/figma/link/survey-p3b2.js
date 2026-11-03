// design-02 П3б2 (T-20261103-09, Desktop): обзор своей страницы (только чтение) — наборы, свойства, варианты
// (размер, раскладка корня, число узлов) и счёт рамок с метками remlab/css (кандидаты на замену). Одна страница на вызов.
const PAGE_ID = '9:2';
const page = await figma.getNodeByIdAsync(PAGE_ID);
await figma.setCurrentPageAsync(page);
const tag = n => n.getSharedPluginData('remlab', 'css');
const out = { page: page.name, top: [] };
for (const sec of page.children) {
  const o = { id: sec.id, t: sec.type, n: sec.name, sets: [] };
  const sets = sec.type === 'COMPONENT_SET' ? [sec] : ('findAllWithCriteria' in sec ? sec.findAllWithCriteria({ types: ['COMPONENT_SET'] }) : []);
  for (const s of sets) {
    const css = {};
    s.findAll(n => n.type === 'FRAME' && !!tag(n) && !n.id.startsWith('I')).forEach(n => { css[tag(n)] = (css[tag(n)] || 0) + 1; });
    const inst = {};
    s.findAllWithCriteria({ types: ['INSTANCE'] }).filter(n => !n.id.startsWith('I')).forEach(n => { const k = (tag(n) || n.name); inst[k] = (inst[k] || 0) + 1; });
    o.sets.push({ id: s.id, n: s.name, props: Object.entries(s.componentPropertyDefinitions).map(([k, d]) => k.replace(/#.*/, '') + ':' + d.type[0] + (d.type === 'VARIANT' ? '[' + d.variantOptions.join('/') + ']' : '')),
      v: s.children.map(v => v.id + ' ' + v.name + ' ' + Math.round(v.width) + 'x' + Math.round(v.height) + ' ' + (v.layoutMode || '') + ' n=' + v.findAll(() => true).length),
      css, inst });
  }
  out.top.push(o);
}
return out;
