// design-02 П3б (T-20261103-08, помощник p3b1, книга Desktop): копия survey-p2b1.js — сжатый обзор страницы элементов (только чтение).
// Для каждого набора/компонента: варианты, свойства (имя:тип), сводка слоёв с меткой remlab/css по типу
// (FRAME/INSTANCE/…), пример (id, размер, текст), уже вложенные экземпляры. Одна страница на вызов: PAGE_ID.
const PAGE_ID = '7:23';

const page = await figma.getNodeByIdAsync(PAGE_ID);
await figma.setCurrentPageAsync(page);
const owners = page.findAllWithCriteria({ types: ['COMPONENT_SET', 'COMPONENT'] }).filter(n => n.type === 'COMPONENT_SET' || n.parent.type !== 'COMPONENT_SET');
const out = { page: page.name, owners: [] };
for (const s of owners) {
  const defs = s.componentPropertyDefinitions;
  const o = { id: s.id, t: s.type === 'COMPONENT_SET' ? 'SET' : 'C', name: s.name, xy: [Math.round(s.x), Math.round(s.y)],
    props: Object.entries(defs).map(([k, d]) => k.replace(/#[^#]*$/, '') + ':' + d.type[0] + (d.variantOptions ? '[' + d.variantOptions.join('/') + ']' : '')),
    variants: s.type === 'COMPONENT_SET' ? s.children.map(v => v.id + ' ' + v.name + ' ' + Math.round(v.width) + 'x' + Math.round(v.height)) : [], css: {}, inst: [] };
  const roots = s.type === 'COMPONENT_SET' ? s.children : [s];
  for (const v of roots) {
    for (const n of v.findAll(n => !n.id.startsWith('I'))) {
      if (n.type === 'INSTANCE') { const mc = await n.getMainComponentAsync(); o.inst.push(n.id + '→' + (mc && mc.id)); }
      const css = n.getSharedPluginData('remlab', 'css');
      if (!css) continue;
      const k = css + ' ' + n.type[0];
      if (!o.css[k]) { const t = n.type === 'TEXT' ? n : (n.findAll ? n.findAll(x => x.type === 'TEXT')[0] : null); o.css[k] = { n: 0, ex: n.id + ' ' + Math.round(n.width) + 'x' + Math.round(n.height) + (t ? ' «' + t.characters.slice(0, 24) + '»' : '') }; }
      o.css[k].n++;
    }
  }
  o.css = Object.entries(o.css).map(([k, v]) => k + ' ×' + v.n + ' ' + v.ex);
  if (o.inst.length > 12) o.inst = o.inst.slice(0, 12).concat(['…' + o.inst.length]);
  out.owners.push(o);
}
return out;
