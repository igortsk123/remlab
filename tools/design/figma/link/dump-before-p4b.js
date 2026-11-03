// design-02 П4б (T-20261103-12): ТОЛЬКО ЧТЕНИЕ — снимок «до/после» одной страницы для отката и сверки.
// Подставить PAGE_ID. Возвращает JSON:
//  page {id,name}; sets [{id,t,n,d,p:{ключ:тип},v:[[id,имя,описание?]]}] (t: S — набор, C — одиночный);
//  inst {mainComponentId: число экземпляров на странице}; txt [[id, characters]] — только для страницы 0:1;
//  dz — работа дизайнера (только 123:2, x ≥ 3900): [[id, mainId, отпечаток переопределений]].
const PAGE_ID = '__PAGE__';
const page = await figma.getNodeByIdAsync(PAGE_ID);
await figma.setCurrentPageAsync(page);
const out = { page: { id: page.id, name: page.name }, sets: [], inst: {}, txt: [], dz: [] };
for (const n of page.findAllWithCriteria({ types: ['COMPONENT_SET', 'COMPONENT'] })) {
  if (n.type === 'COMPONENT' && n.parent && n.parent.type === 'COMPONENT_SET') continue;
  const defs = n.componentPropertyDefinitions;
  const p = {};
  for (const k of Object.keys(defs)) p[k] = defs[k].type[0] + (defs[k].type === 'VARIANT' ? '' : '=' + (defs[k].type === 'INSTANCE_SWAP' ? 'swap' : defs[k].defaultValue));
  const row = { id: n.id, t: n.type === 'COMPONENT_SET' ? 'S' : 'C', n: n.name, d: n.description || '', p };
  if (n.type === 'COMPONENT_SET') row.v = n.children.map(c => c.description ? [c.id, c.name, c.description] : [c.id, c.name]);
  out.sets.push(row);
}
const insts = page.findAllWithCriteria({ types: ['INSTANCE'] });
const mains = await Promise.all(insts.map(i => i.getMainComponentAsync()));
mains.forEach(m => { const k = m ? m.id : 'null'; out.inst[k] = (out.inst[k] || 0) + 1; });
if (PAGE_ID === '0:1') {
  for (const t of page.findAllWithCriteria({ types: ['TEXT'] })) out.txt.push([t.id, t.characters]);
}
if (PAGE_ID === '123:2') {
  const h = s => { let x = 5381; for (let i = 0; i < s.length; i++) x = ((x * 33) ^ s.charCodeAt(i)) >>> 0; return x.toString(36); };
  insts.forEach((i, k) => {
    if (i.absoluteTransform[0][2] < 3900) return;
    const sub = i.findAll(() => true).map(d => d.id.split(';').pop() + (d.visible ? '' : '!') + ('characters' in d ? '=' + d.characters : '')).join('|');
    const ov = (i.overrides || []).map(o => o.id.split(';').pop() + ':' + o.overriddenFields.join(',')).join('|');
    out.dz.push([i.id, mains[k] ? mains[k].id : null, h(sub), h(ov), Math.round(i.width) + 'x' + Math.round(i.height)]);
  });
}
return JSON.stringify(out);
