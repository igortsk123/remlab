// design-02 П4а (T-20261103-11): ТОЛЬКО ЧТЕНИЕ — наборы компонентов и одиночные компоненты страницы элементов
// для таблицы имён naming.json. Одна страница на вызов: подставить PAGE_ID. Строка на набор:
// S|id|имя|описание|свойства|варианты   (C — одиночный компонент, без вариантов)
// свойства: имя:тип=по_умолчанию[{варианты через /}] через ;  варианты: значения через «,», разделитель ¦
const PAGE_ID = '__PAGE__';
const page = await figma.getNodeByIdAsync(PAGE_ID);
await figma.setCurrentPageAsync(page);
const esc = s => String(s).replace(/[|\n¦]/g, m => (m === '\n' ? '\\n' : m === '|' ? '\\|' : '\\¦'));
const defs = d => Object.entries(d).map(([k, v]) => k + ':' + v.type[0] + '=' + (v.type === 'INSTANCE_SWAP' ? 'swap' : v.defaultValue) + (v.variantOptions ? '{' + v.variantOptions.join('/') + '}' : '')).join(';');
const rows = [];
for (const n of page.findAllWithCriteria({ types: ['COMPONENT_SET', 'COMPONENT'] })) {
  if (n.type === 'COMPONENT' && n.parent && n.parent.type === 'COMPONENT_SET') continue;
  const inComp = (() => { let p = n.parent; while (p && p.type !== 'PAGE') { if (p.type === 'COMPONENT' || p.type === 'COMPONENT_SET') return p.id; p = p.parent; } return ''; })();
  const pd = defs(n.componentPropertyDefinitions);
  // варианты — значения свойств по порядку ключей; имя, расходящееся с каноном «k=v, k=v», — целиком после «!»
  const canon = c => Object.entries(c.variantProperties || {}).map(([k, v]) => k + '=' + v).join(', ');
  const vars = n.type === 'COMPONENT_SET' ? n.children.map(c => esc(Object.values(c.variantProperties || {}).join(',')) + (c.name !== canon(c) ? '!' + esc(c.name) : '')).join('¦') : '';
  // описания вариантов: только если отличаются от пустых (обычно пусто)
  const vdesc = n.type === 'COMPONENT_SET' ? n.children.filter(c => c.description).map(c => c.id + '=' + esc(c.description)).join('¦') : '';
  rows.push([n.type === 'COMPONENT_SET' ? 'S' : 'C', n.id, esc(n.name), esc(n.description || ''), esc(pd), vars, vdesc, inComp, Math.round(n.x)].join('|'));
}
return page.name + '\n' + rows.join('\n');
